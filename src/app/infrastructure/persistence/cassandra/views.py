"""Position-bucketed history and a repairable, sequenced journal per user."""

from uuid import UUID

from cassandra.cluster import Session
from pydantic import BaseModel, Field

from app.application.dto.messages import MessageDTO
from app.application.dto.reading import DialogBatch, DialogSummary, SyncBatch, SyncEntry
from app.application.exceptions.dependencies import (
    ProjectionUnavailableError,
    StorageUnavailableError,
)
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.saved_dialog import SavedDialog
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.limits import (
    BUCKET_SIZE,
    MAX_ATTEMPTS,
    MAX_PAGE_SIZE,
    MAX_USER_PENDING_BYTES,
    WORK_CAPACITY,
)
from app.infrastructure.persistence.cassandra.records import (
    PayloadRow,
    SequenceRow,
    VersionedRow,
    storage_boundary,
)
from app.infrastructure.persistence.cassandra.statements import (
    conditional_write,
    serial_read,
)

type Dialog = DirectDialog | SavedDialog


class _Change(BaseModel):
    key: str
    sequence: int
    dialog: DirectDialog | SavedDialog
    event_id: UUID
    event_type: str
    message: Message | None = Field(default=None)


class _State(BaseModel):
    last_sequence: int = Field(default=0)
    published_sequence: int = Field(default=0)
    pending: tuple[_Change, ...] = Field(default=())


class _Card(BaseModel):
    last_position: int
    payload: str


def summary(dialog: Dialog, message: Message | None = None) -> DialogSummary:
    return DialogSummary(
        id=dialog.id,
        kind="DIRECT" if isinstance(dialog, DirectDialog) else "SAVED",
        participant_ids=dialog.as_tuple
        if isinstance(dialog, DirectDialog)
        else (dialog.user_id,),
        created_at=dialog.created_at,
        last_position=message.position.value if message else 0,
        last_message=MessageDTO.from_domain(message) if message else None,
    )


class CassandraMessageViews:
    def __init__(self, session: Session | AsyncCassandraSession) -> None:
        self.session = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )

    async def _state(self, user_id: UUID) -> tuple[int, _State]:
        page = await self.session.execute(
            serial_read(
                "SELECT revision, payload FROM user_projection_state WHERE user_id=%s"
            ),
            (user_id,),
        )
        row = page.one()
        if row is None:
            return 0, _State()
        record = VersionedRow.model_validate(row, from_attributes=True)
        return record.revision, _State.model_validate_json(record.payload)

    async def _sequence(self, user_id: UUID, key: str) -> int | None:
        page = await self.session.execute(
            serial_read(
                "SELECT sequence FROM user_projection_results WHERE user_id=%s AND event_key=%s"
            ),
            (user_id, key),
        )
        row = page.one()
        return (
            SequenceRow.model_validate(row, from_attributes=True).sequence
            if row
            else None
        )

    async def _cas(self, user_id: UUID, revision: int, state: _State) -> bool:
        payload = state.model_dump_json()
        if len(payload.encode()) > MAX_USER_PENDING_BYTES:
            raise StorageUnavailableError("User projection backlog is full")
        if revision == 0:
            page = await self.session.execute(
                conditional_write(
                    "INSERT INTO user_projection_state (user_id, revision, payload) VALUES (%s, 1, %s) IF NOT EXISTS"
                ),
                (user_id, payload),
            )
        else:
            page = await self.session.execute(
                conditional_write(
                    "UPDATE user_projection_state SET revision=%s, payload=%s WHERE user_id=%s IF revision=%s"
                ),
                (revision + 1, payload, user_id, revision),
            )
        return page.was_applied

    async def _effect(self, user_id: UUID, change: _Change) -> None:
        if change.message is None:
            ordinal = change.sequence
            await self.session.execute(
                conditional_write(
                    "INSERT INTO user_dialogs (user_id, bucket, ordinal, last_position, payload) VALUES (%s, %s, %s, 0, %s) IF NOT EXISTS"
                ),
                (
                    user_id,
                    (ordinal - 1) // BUCKET_SIZE,
                    ordinal,
                    summary(change.dialog).model_dump_json(),
                ),
            )
        else:
            ordinal = await self._sequence(user_id, "dialog:" + str(change.dialog.id))
            if ordinal is None:
                raise StorageUnavailableError("Dialog projection is incomplete")
            await self.session.execute(
                conditional_write(
                    "UPDATE user_dialogs SET last_position=%s, payload=%s WHERE user_id=%s AND bucket=%s AND ordinal=%s IF last_position < %s"
                ),
                (
                    change.message.position.value,
                    summary(change.dialog, change.message).model_dump_json(),
                    user_id,
                    (ordinal - 1) // BUCKET_SIZE,
                    ordinal,
                    change.message.position.value,
                ),
            )
            page = await self.session.execute(
                serial_read(
                    "SELECT last_position, payload FROM user_dialogs WHERE user_id=%s AND bucket=%s AND ordinal=%s"
                ),
                (user_id, (ordinal - 1) // BUCKET_SIZE, ordinal),
            )
            if (
                _Card.model_validate(page.one(), from_attributes=True).last_position
                < change.message.position.value
            ):
                raise StorageUnavailableError("Activity projection is incomplete")
        entry = SyncEntry(
            sequence=change.sequence,
            event_id=change.event_id,
            type=change.event_type,
            dialog_id=change.dialog.id,
            message=MessageDTO.from_domain(change.message) if change.message else None,
        )
        await self.session.execute(
            conditional_write(
                "INSERT INTO user_sync (user_id, bucket, sequence, payload) VALUES (%s, %s, %s, %s) IF NOT EXISTS"
            ),
            (
                user_id,
                (change.sequence - 1) // BUCKET_SIZE,
                change.sequence,
                entry.model_dump_json(),
            ),
        )
        await self.session.execute(
            conditional_write(
                "INSERT INTO user_projection_results (user_id, event_key, sequence) VALUES (%s, %s, %s) IF NOT EXISTS"
            ),
            (user_id, change.key, change.sequence),
        )

    async def _drain(self, user_id: UUID) -> None:
        for _ in range(MAX_ATTEMPTS):
            revision, state = await self._state(user_id)
            if not state.pending:
                return
            for change in state.pending:
                await self._effect(user_id, change)
            cleared = _State(
                last_sequence=state.last_sequence,
                published_sequence=state.last_sequence,
            )
            if await self._cas(user_id, revision, cleared):
                return
        raise StorageUnavailableError("User projection is busy")

    async def _append(self, user_id: UUID, change: _Change) -> None:
        for _ in range(MAX_ATTEMPTS):
            revision, state = await self._state(user_id)
            # Read the durable receipt AFTER the head. Retirement advances revision,
            # fencing a stale absence that could otherwise allocate a second sequence.
            if await self._sequence(user_id, change.key) is not None or any(
                item.key == change.key for item in state.pending
            ):
                await self._drain(user_id)
                return
            if len(state.pending) >= WORK_CAPACITY:
                raise StorageUnavailableError("User projection backlog is full")
            sequence = state.last_sequence + 1
            next_change = change.model_copy(update={"sequence": sequence})
            next_state = _State(
                last_sequence=sequence,
                published_sequence=state.published_sequence,
                pending=(*state.pending, next_change),
            )
            if await self._cas(user_id, revision, next_state):
                await self._drain(user_id)
                return
        raise StorageUnavailableError("User projection acceptance is busy")

    @storage_boundary
    async def ensure_for_user(
        self, user_id: UUID, dialog: DirectDialog | SavedDialog | GroupDialog
    ) -> None:
        if isinstance(dialog, GroupDialog):
            raise ProjectionUnavailableError(
                "Group views are not enabled in the Direct slice"
            )
        dialog.require_can_read(user_id)
        await self._append(
            user_id,
            _Change(
                key="dialog:" + str(dialog.id),
                sequence=0,
                dialog=dialog,
                event_id=dialog.id,
                event_type="dialog.created",
            ),
        )

    @storage_boundary
    async def project_message(
        self,
        user_id: UUID,
        dialog: Dialog,
        message: Message,
        *,
        event_id: UUID,
        event_type: str,
    ) -> None:
        await self.ensure_for_user(user_id, dialog)
        await self._append(
            user_id,
            _Change(
                key=str(event_id),
                sequence=0,
                dialog=dialog,
                event_id=event_id,
                event_type=event_type,
                message=message,
            ),
        )

    @storage_boundary
    async def store_message(self, message: Message) -> None:
        payload = message.model_dump_json()
        await self.session.execute(
            conditional_write(
                "INSERT INTO message_history (dialog_id, bucket, position, payload) VALUES (%s, %s, %s, %s) IF NOT EXISTS"
            ),
            (
                message.dialog_id,
                (message.position.value - 1) // BUCKET_SIZE,
                message.position.value,
                payload,
            ),
        )
        await self.session.execute(
            conditional_write(
                "INSERT INTO message_lookup (dialog_id, message_id, payload) VALUES (%s, %s, %s) IF NOT EXISTS"
            ),
            (message.dialog_id, message.id, payload),
        )

    @storage_boundary
    async def get_message(self, dialog_id: UUID, message_id: UUID) -> Message | None:
        page = await self.session.execute(
            serial_read(
                "SELECT payload FROM message_lookup WHERE dialog_id=%s AND message_id=%s"
            ),
            (dialog_id, message_id),
        )
        row = page.one()
        return (
            Message.model_validate_json(
                PayloadRow.model_validate(row, from_attributes=True).payload
            )
            if row
            else None
        )

    @storage_boundary
    async def get_dialog(self, user_id: UUID, dialog_id: UUID) -> DialogSummary | None:
        ordinal = await self._sequence(user_id, "dialog:" + str(dialog_id))
        if ordinal is None:
            return None
        page = await self.session.execute(
            serial_read(
                "SELECT payload FROM user_dialogs WHERE user_id=%s AND bucket=%s AND ordinal=%s"
            ),
            (user_id, (ordinal - 1) // BUCKET_SIZE, ordinal),
        )
        row = page.one()
        return (
            DialogSummary.model_validate_json(
                PayloadRow.model_validate(row, from_attributes=True).payload
            )
            if row
            else None
        )

    @storage_boundary
    async def history(
        self, dialog_id: UUID, *, after: int, through: int, limit: int
    ) -> tuple[Message, ...]:
        if not 1 <= limit <= MAX_PAGE_SIZE or after < 0 or through < after:
            raise ValueError("Invalid history range")
        items: list[Message] = []
        position = after + 1
        while position <= through and len(items) < limit:
            bucket = (position - 1) // BUCKET_SIZE
            end = min(through, (bucket + 1) * BUCKET_SIZE)
            page = await self.session.execute(
                serial_read(
                    "SELECT payload FROM message_history WHERE dialog_id=%s AND bucket=%s AND position >= %s AND position <= %s LIMIT %s"
                ),
                (dialog_id, bucket, position, end, limit - len(items)),
            )
            items.extend(
                Message.model_validate_json(
                    PayloadRow.model_validate(row, from_attributes=True).payload
                )
                for row in page.current_rows
            )
            position = end + 1
        return tuple(items)

    @storage_boundary
    async def sync(
        self, user_id: UUID, *, after: int, through: int | None, limit: int
    ) -> SyncBatch:
        _, state = await self._state(user_id)
        ceiling = (
            state.published_sequence
            if through is None
            else min(through, state.published_sequence)
        )
        if not 1 <= limit <= MAX_PAGE_SIZE or not 0 <= after <= ceiling:
            raise ValueError("Invalid sync range")
        items: list[SyncEntry] = []
        position = after + 1
        while position <= ceiling and len(items) < limit:
            bucket = (position - 1) // BUCKET_SIZE
            end = min(ceiling, (bucket + 1) * BUCKET_SIZE)
            page = await self.session.execute(
                serial_read(
                    "SELECT payload FROM user_sync WHERE user_id=%s AND bucket=%s AND sequence >= %s AND sequence <= %s LIMIT %s"
                ),
                (user_id, bucket, position, end, limit - len(items)),
            )
            items.extend(
                SyncEntry.model_validate_json(
                    PayloadRow.model_validate(row, from_attributes=True).payload
                )
                for row in page.current_rows
            )
            position = end + 1
        return SyncBatch(items=tuple(items), through=ceiling)

    @storage_boundary
    async def dialogs(
        self, user_id: UUID, *, after: int, through: int | None, limit: int
    ) -> DialogBatch:
        _, state = await self._state(user_id)
        ceiling = (
            state.published_sequence
            if through is None
            else min(through, state.published_sequence)
        )
        if not 1 <= limit <= MAX_PAGE_SIZE or not 0 <= after <= ceiling:
            raise ValueError("Invalid dialog range")
        items: list[DialogSummary] = []
        position = after + 1
        # Sparse dialog ordinals share the user journal sequence. Bound work per
        # request even when a user has sent many messages in a single dialog.
        last_scanned = after
        for _ in range(4):
            if position > ceiling or len(items) >= limit:
                break
            bucket = (position - 1) // BUCKET_SIZE
            end = min(ceiling, (bucket + 1) * BUCKET_SIZE)
            page = await self.session.execute(
                serial_read(
                    "SELECT ordinal, payload FROM user_dialogs WHERE user_id=%s AND bucket=%s AND ordinal >= %s AND ordinal <= %s LIMIT %s"
                ),
                (user_id, bucket, position, end, limit - len(items)),
            )

            class CardRow(PayloadRow):
                ordinal: int

            rows = [
                CardRow.model_validate(row, from_attributes=True)
                for row in page.current_rows
            ]
            items.extend(DialogSummary.model_validate_json(row.payload) for row in rows)
            last_scanned = rows[-1].ordinal if len(items) >= limit else end
            position = end + 1
        return DialogBatch(items=tuple(items), through=last_scanned, upper=ceiling)
