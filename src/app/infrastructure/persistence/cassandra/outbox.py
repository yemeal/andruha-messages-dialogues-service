"""Durable event envelopes and lease-fenced publisher claims."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from cassandra.cluster import Session

from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.ports.dto.outbox import OutboxMessage, OutboxStatus
from app.domain.clock import utc_now
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.limits import WORK_CAPACITY
from app.infrastructure.persistence.cassandra.records import (
    VersionedRow,
    storage_boundary,
)
from app.infrastructure.persistence.cassandra.statements import (
    DRIVER_ERRORS,
    conditional_write,
    serial_read,
)
from app.infrastructure.persistence.cassandra.work import CassandraWork


class CassandraOutbox:
    def __init__(
        self,
        session: Session | AsyncCassandraSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )
        self.work = CassandraWork(self.session, kind="outbox")
        self.clock = clock

    async def _get(self, event_id: UUID) -> tuple[int, OutboxMessage] | None:
        page = await self.session.execute(
            serial_read(
                "SELECT revision, payload FROM message_outbox WHERE event_id=%s"
            ),
            (event_id,),
        )
        row = page.one()
        if row is None:
            return None
        record = VersionedRow.model_validate(row, from_attributes=True)
        return record.revision, OutboxMessage.model_validate_json(record.payload)

    async def _ensure(self, message: OutboxMessage) -> tuple[int, OutboxMessage]:
        await self.session.execute(
            conditional_write(
                "INSERT INTO message_outbox (event_id, revision, payload) VALUES (%s, 1, %s) IF NOT EXISTS"
            ),
            (message.id, message.model_dump_json()),
        )
        record = await self._get(message.id)
        if record is None:
            raise StorageUnavailableError("Outbox insert outcome is unknown")
        current = record[1]
        if (
            current.payload != message.payload
            or current.topic != message.topic
            or current.key != message.key
            or current.type != message.type
        ):
            raise StorageUnavailableError("Event identity conflicts")
        return record

    async def _cas(self, revision: int, message: OutboxMessage) -> bool:
        try:
            page = await self.session.execute(
                conditional_write(
                    "UPDATE message_outbox SET revision=%s, payload=%s WHERE event_id=%s IF revision=%s"
                ),
                (revision + 1, message.model_dump_json(), message.id, revision),
            )
            return page.was_applied
        except DRIVER_ERRORS as error:
            record = await self._get(message.id)
            if record is not None and record[1] == message:
                return True
            raise StorageUnavailableError(
                "Outbox transition outcome is unknown"
            ) from error

    @storage_boundary
    async def save_messages(self, messages: tuple[OutboxMessage, ...]) -> None:
        for message in messages:
            record = await self._get(message.id)
            if record is not None and record[1].status in (
                OutboxStatus.SUCCESS,
                OutboxStatus.QUARANTINED,
            ):
                if record[1].payload != message.payload:
                    raise StorageUnavailableError("Event identity conflicts")
                continue
            await self.work.enqueue(str(message.id), message.model_dump_json())
            await self._ensure(message)

    @storage_boundary
    async def claim_batch(
        self,
        *,
        owner_token: UUID,
        claimed_at: datetime,
        claim_expires_at: datetime,
        limit: int,
    ) -> list[OutboxMessage]:
        if not 1 <= limit <= WORK_CAPACITY or claim_expires_at <= claimed_at:
            raise ValueError("Invalid outbox claim")
        claimed: list[OutboxMessage] = []
        for task in await self.work.pending(limit=WORK_CAPACITY):
            original = OutboxMessage.model_validate_json(task.payload)
            revision, current = await self._ensure(original)
            if current.status in (OutboxStatus.SUCCESS, OutboxStatus.QUARANTINED):
                await self.work.remove(str(current.id), task.payload)
                continue
            if current.available_at > claimed_at:
                continue
            if (
                current.status == OutboxStatus.CLAIMED
                and current.claim_expires_at is not None
                and current.claim_expires_at > claimed_at
            ):
                continue
            candidate = OutboxMessage.model_validate(
                current.model_dump()
                | {
                    "status": OutboxStatus.CLAIMED,
                    "claim_token": owner_token,
                    "claim_expires_at": claim_expires_at,
                    "attempts": current.attempts + 1,
                    "updated_at": claimed_at,
                }
            )
            if await self._cas(revision, candidate):
                claimed.append(candidate)
            if len(claimed) >= limit:
                break
        return claimed

    async def _transition(
        self,
        event_id: UUID,
        owner_token: UUID,
        *,
        now: datetime,
        status: OutboxStatus,
        available_at: datetime | None = None,
        error_class: str | None = None,
    ) -> bool:
        record = await self._get(event_id)
        if record is None:
            return False
        revision, current = record
        if (
            current.status != OutboxStatus.CLAIMED
            or current.claim_token != owner_token
            or current.claim_expires_at is None
            or current.claim_expires_at <= now
        ):
            return False
        terminal = status in (OutboxStatus.SUCCESS, OutboxStatus.QUARANTINED)
        candidate = OutboxMessage.model_validate(
            current.model_dump()
            | {
                "status": status,
                "claim_token": None,
                "claim_expires_at": None,
                "terminal_at": now if terminal else None,
                "updated_at": now,
                "available_at": available_at or current.available_at,
                "last_error_class": error_class,
            }
        )
        return await self._cas(revision, candidate)

    @storage_boundary
    async def finalize_published(
        self, message_id: UUID, *, owner_token: UUID, published_at: datetime
    ) -> bool:
        return await self._transition(
            message_id, owner_token, now=published_at, status=OutboxStatus.SUCCESS
        )

    @storage_boundary
    async def schedule_retry(
        self,
        message_id: UUID,
        *,
        owner_token: UUID,
        available_at: datetime,
        error_class: str = "TransientPublishError",
    ) -> bool:
        return await self._transition(
            message_id,
            owner_token,
            now=self.clock(),
            status=OutboxStatus.PENDING,
            available_at=available_at,
            error_class=error_class,
        )

    @storage_boundary
    async def quarantine(
        self,
        message_id: UUID,
        *,
        owner_token: UUID,
        quarantined_at: datetime,
        error_class: str = "PermanentOutboxPublishError",
    ) -> bool:
        return await self._transition(
            message_id,
            owner_token,
            now=quarantined_at,
            status=OutboxStatus.QUARANTINED,
            error_class=error_class,
        )
