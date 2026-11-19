"""Global send reservations and dialog-local, conditional message acceptance."""

from contextlib import suppress
from uuid import UUID

from cassandra.cluster import Session
from pydantic import BaseModel, ValidationError

from app.application.events.factory import EventFactory
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import MessageSendConflictError
from app.application.ports.dto.outbox import OutboxMessage
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.message_position import MessagePosition
from app.domain.value_objects.message_send_key import MessageSendKey
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.limits import MAX_ATTEMPTS, WORK_CAPACITY
from app.infrastructure.persistence.cassandra.outbox import CassandraOutbox
from app.infrastructure.persistence.cassandra.records import storage_boundary
from app.infrastructure.persistence.cassandra.statements import (
    DRIVER_ERRORS,
    conditional_write,
    serial_read,
)
from app.infrastructure.persistence.cassandra.views import CassandraMessageViews
from app.infrastructure.persistence.cassandra.work import CassandraWork

MAX_SEND_ATTEMPTS = 32
MAX_WORKING_COMMANDS = 256


class _Head(BaseModel):
    command_kind: str
    revision: int
    last_position: int
    pending_count: int
    payload: str


class _Payload(BaseModel):
    payload: str


class _Result(BaseModel):
    result: str


class SendAcceptance(BaseModel):
    message: Message
    events: tuple[OutboxMessage, ...]


class _Archive(BaseModel):
    acceptance: str | None


def send_identity(key: MessageSendKey) -> str:
    return f"{key.sender_id}:{key.client_message_id.value}"


def require_same_send(existing: Message, candidate: Message) -> None:
    if (
        existing.dialog_id != candidate.dialog_id
        or existing.send_key != candidate.send_key
        or existing.content.attachments != candidate.content.attachments
        or (not existing.is_edited and existing.content != candidate.content)
    ):
        raise MessageSendConflictError()


class CassandraMessages:
    def __init__(
        self,
        session: Session | AsyncCassandraSession,
        *,
        timeout_seconds: float = 5,
    ) -> None:
        self.session = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )
        self.timeout = timeout_seconds
        self.views = CassandraMessageViews(self.session)
        self.outbox = CassandraOutbox(self.session)
        self.work = CassandraWork(self.session, kind="sends")
        self.events = EventFactory()

    async def _head(self, dialog_id: UUID) -> _Head:
        result = await self.session.execute(
            serial_read(
                "SELECT command_kind, revision, last_position, pending_count, payload "
                "FROM canonical_rows WHERE dialog_id=%s AND row_key='state'"
            ),
            (dialog_id,),
            timeout=self.timeout,
        )
        row = result.one()
        if row is None:
            raise StorageUnavailableError("Canonical dialog is missing")
        return _Head.model_validate(row, from_attributes=True)

    async def _reservation(self, key: MessageSendKey) -> Message | None:
        result = await self.session.execute(
            serial_read(
                "SELECT payload FROM message_sends "
                "WHERE sender_id=%s AND client_message_id=%s"
            ),
            (key.sender_id, key.client_message_id.value),
            timeout=self.timeout,
        )
        row = result.one()
        if row is None:
            return None
        message = Message.model_validate_json(
            _Payload.model_validate(row, from_attributes=True).payload
        )
        if message.send_key != key:
            raise StorageUnavailableError("Send reservation identity is inconsistent")
        return message

    async def _archived(self, key: MessageSendKey) -> SendAcceptance | None:
        page = await self.session.execute(
            serial_read(
                "SELECT acceptance FROM message_sends WHERE sender_id=%s AND client_message_id=%s"
            ),
            (key.sender_id, key.client_message_id.value),
        )
        row = page.one()
        value = (
            _Archive.model_validate(row, from_attributes=True).acceptance
            if row
            else None
        )
        return SendAcceptance.model_validate_json(value) if value else None

    async def _working(self, message: Message) -> SendAcceptance | None:
        result = await self.session.execute(
            serial_read(
                "SELECT result FROM canonical_rows WHERE dialog_id=%s AND row_key=%s"
            ),
            (message.dialog_id, "send:" + send_identity(message.send_key)),
            timeout=self.timeout,
        )
        row = result.one()
        if row is None:
            return None
        return SendAcceptance.model_validate_json(
            _Result.model_validate(row, from_attributes=True).result
        )

    async def _accepted(self, message: Message) -> SendAcceptance | None:
        return await self._working(message) or await self._archived(message.send_key)

    async def _accept(self, reserved: Message) -> SendAcceptance:
        await self.work.enqueue(
            send_identity(reserved.send_key), reserved.send_key.model_dump_json()
        )
        for _ in range(MAX_SEND_ATTEMPTS):
            head = await self._head(reserved.dialog_id)
            existing = await self._accepted(reserved)
            if existing is not None:
                return existing
            if head.command_kind == "DIRECT":
                DirectDialog.model_validate_json(head.payload).require_can_send(
                    reserved.sender_id
                )
            elif head.command_kind == "SAVED":
                SavedDialog.model_validate_json(head.payload).require_can_send(
                    reserved.sender_id
                )
            else:
                raise StorageUnavailableError(
                    "Message adapter requires Direct or Saved"
                )
            if head.pending_count >= MAX_WORKING_COMMANDS:
                raise StorageUnavailableError("Canonical recovery backlog is full")
            message = reserved.model_copy(
                update={
                    "position": MessagePosition(
                        dialog_id=reserved.dialog_id, value=head.last_position + 1
                    )
                }
            )
            if head.command_kind == "DIRECT":
                dialog = DirectDialog.model_validate_json(head.payload)
                recipients = (dialog.peer_of(message.sender_id),)
            else:
                recipients = ()
            acceptance = SendAcceptance(
                message=message,
                events=(
                    self.events.create_message_persisted(
                        message=message,
                        correlation_id=message.client_message_id.value,
                        occurred_at=message.created_at,
                    ),
                    *self.events.create_message_created_batch(
                        message=message,
                        recipient_ids=recipients,
                        correlation_id=message.client_message_id.value,
                        occurred_at=message.created_at,
                    ),
                ),
            )
            try:
                result = await self.session.execute(
                    conditional_write(
                        "BEGIN BATCH "
                        "UPDATE canonical_rows SET revision=%s, last_position=%s, "
                        "pending_count=%s WHERE dialog_id=%s AND row_key='state' "
                        "IF revision=%s; "
                        "INSERT INTO canonical_rows "
                        "(dialog_id, row_key, command_kind, revision, result) "
                        "VALUES (%s, %s, 'send', %s, %s) IF NOT EXISTS; "
                        "APPLY BATCH"
                    ),
                    (
                        head.revision + 1,
                        message.position.value,
                        head.pending_count + 1,
                        message.dialog_id,
                        head.revision,
                        message.dialog_id,
                        "send:" + send_identity(message.send_key),
                        head.revision + 1,
                        acceptance.model_dump_json(),
                    ),
                    timeout=self.timeout,
                )
            except DRIVER_ERRORS as error:
                existing = await self._accepted(reserved)
                if existing is not None:
                    return existing
                raise StorageUnavailableError(
                    "Message acceptance outcome is unknown"
                ) from error
            if result.was_applied:
                return acceptance
        raise StorageUnavailableError("Message acceptance is busy; retry the same send")

    async def _retire(self, accepted: SendAcceptance) -> None:
        message = accepted.message
        for _ in range(MAX_ATTEMPTS):
            head = await self._head(message.dialog_id)
            if await self._working(message) is None:
                return
            page = await self.session.execute(
                conditional_write(
                    "BEGIN BATCH UPDATE canonical_rows SET revision=%s, pending_count=%s "
                    "WHERE dialog_id=%s AND row_key='state' IF revision=%s; "
                    "DELETE FROM canonical_rows WHERE dialog_id=%s AND row_key=%s "
                    "IF result=%s; APPLY BATCH"
                ),
                (
                    head.revision + 1,
                    head.pending_count - 1,
                    message.dialog_id,
                    head.revision,
                    message.dialog_id,
                    "send:" + send_identity(message.send_key),
                    accepted.model_dump_json(),
                ),
            )
            if page.was_applied:
                return
        raise StorageUnavailableError("Canonical projection retirement is busy")

    async def _complete(self, accepted: SendAcceptance) -> Message:
        message = accepted.message
        if await self._archived(message.send_key) is None:
            head = await self._head(message.dialog_id)
            dialog = (
                DirectDialog.model_validate_json(head.payload)
                if head.command_kind == "DIRECT"
                else SavedDialog.model_validate_json(head.payload)
            )
            await self.views.store_message(message)
            for event in accepted.events:
                target = UUID(event.key)
                await self.views.project_message(
                    target, dialog, message, event_id=event.id, event_type=event.type
                )
            await self.outbox.save_messages(accepted.events)
            await self.session.execute(
                conditional_write(
                    "UPDATE message_sends SET acceptance=%s, payload=%s WHERE sender_id=%s AND client_message_id=%s IF acceptance=null"
                ),
                (
                    accepted.model_dump_json(),
                    message.model_dump_json(),
                    message.sender_id,
                    message.client_message_id.value,
                ),
            )
            archive = await self._archived(message.send_key)
            if archive != accepted:
                raise StorageUnavailableError("Send projections were not confirmed")
        await self._retire(accepted)
        await self.work.remove(
            send_identity(message.send_key), message.send_key.model_dump_json()
        )
        return message

    async def get_by_send_key(self, send_key: MessageSendKey) -> Message | None:
        try:
            reserved = await self._reservation(send_key)
            return (
                await self._complete(await self._accept(reserved))
                if reserved is not None
                else None
            )
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError("Send read unavailable") from error

    async def get_last_position(self, dialog_id: UUID) -> int:
        try:
            return (await self._head(dialog_id)).last_position
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError("Dialog position unavailable") from error

    async def save_message(
        self, message: Message, *, idempotency_key: MessageSendKey
    ) -> Message:
        if message.send_key != idempotency_key:
            raise MessageSendConflictError()
        try:
            # A timeout can hide a successful LWT. Only the SERIAL read decides.
            with suppress(*DRIVER_ERRORS):
                await self.session.execute(
                    conditional_write(
                        "INSERT INTO message_sends (sender_id, client_message_id, payload) "
                        "VALUES (%s, %s, %s) IF NOT EXISTS"
                    ),
                    (
                        idempotency_key.sender_id,
                        idempotency_key.client_message_id.value,
                        message.model_dump_json(),
                    ),
                    timeout=self.timeout,
                )
            reserved = await self._reservation(idempotency_key)
            if reserved is None:
                raise StorageUnavailableError("Send reservation outcome is unknown")
            require_same_send(reserved, message)
            return await self._complete(await self._accept(reserved))
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError("Message storage unavailable") from error

    async def get_message_by_id(
        self, dialog_id: UUID, message_id: UUID
    ) -> Message | None:
        return await self.views.get_message(dialog_id, message_id)

    @storage_boundary
    async def repair_pending(self, *, limit: int = 32) -> int:
        repaired = 0
        for task in await self.work.pending(limit=limit):
            key = MessageSendKey.model_validate_json(task.payload)
            reserved = await self._reservation(key)
            if reserved is None:
                raise StorageUnavailableError("Recovery reservation is missing")
            await self._complete(await self._accept(reserved))
            repaired += 1
        return repaired

    @storage_boundary
    async def history(
        self, dialog_id: UUID, *, after: int, through: int | None, limit: int
    ) -> tuple[tuple[Message, ...], int]:
        for _ in range(MAX_ATTEMPTS):
            head = await self._head(dialog_id)
            ceiling = (
                head.last_position
                if through is None
                else min(through, head.last_position)
            )
            items = await self.views.history(
                dialog_id, after=after, through=ceiling, limit=limit
            )
            pending = await self.session.execute(
                serial_read(
                    "SELECT result FROM canonical_rows WHERE dialog_id=%s AND row_key >= 'send:' AND row_key < 'send;' LIMIT %s"
                ),
                (dialog_id, WORK_CAPACITY),
            )
            overlay = [
                SendAcceptance.model_validate_json(
                    _Result.model_validate(row, from_attributes=True).result
                ).message
                for row in pending.current_rows
            ]
            if (await self._head(dialog_id)).revision != head.revision:
                continue
            by_position = {
                item.position.value: item
                for item in (*items, *overlay)
                if after < item.position.value <= ceiling
            }
            return tuple(
                by_position[pos] for pos in sorted(by_position)[:limit]
            ), ceiling
        raise StorageUnavailableError("History snapshot is busy")
