"""Bounded, durable work discovery. Idempotent repair does not require a lease."""

import hashlib
from contextlib import suppress

from pydantic import BaseModel

from app.application.exceptions.dependencies import StorageUnavailableError
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.limits import (
    MAX_ATTEMPTS,
    WORK_CAPACITY,
    WORK_SHARDS,
)
from app.infrastructure.persistence.cassandra.records import PayloadRow
from app.infrastructure.persistence.cassandra.statements import (
    DRIVER_ERRORS,
    conditional_write,
    serial_read,
)


class WorkItem(BaseModel):
    row_key: str
    payload: str


class _Head(BaseModel):
    revision: int
    pending_count: int


class CassandraWork:
    def __init__(self, session: AsyncCassandraSession, *, kind: str) -> None:
        self.session = session
        self.kind = kind
        self._next_shard = 0

    def shard(self, key: str) -> int:
        return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4]) % WORK_SHARDS

    async def _item(self, shard: int, key: str) -> str | None:
        page = await self.session.execute(
            serial_read(
                "SELECT payload FROM work_rows "
                "WHERE kind=%s AND shard=%s AND row_key=%s"
            ),
            (self.kind, shard, "task:" + key),
        )
        row = page.one()
        return (
            PayloadRow.model_validate(row, from_attributes=True).payload
            if row
            else None
        )

    async def _head(self, shard: int) -> _Head:
        await self.session.execute(
            conditional_write(
                "INSERT INTO work_rows (kind, shard, row_key, revision, pending_count) "
                "VALUES (%s, %s, 'head', 0, 0) IF NOT EXISTS"
            ),
            (self.kind, shard),
        )
        page = await self.session.execute(
            serial_read(
                "SELECT revision, pending_count FROM work_rows "
                "WHERE kind=%s AND shard=%s AND row_key='head'"
            ),
            (self.kind, shard),
        )
        return _Head.model_validate(page.one(), from_attributes=True)

    async def enqueue(self, key: str, payload: str) -> None:
        shard = self.shard(key)
        for _ in range(MAX_ATTEMPTS):
            head = await self._head(shard)
            existing = await self._item(shard, key)
            if existing is not None:
                if existing != payload:
                    raise StorageUnavailableError("Recovery task identity conflicts")
                return
            if head.pending_count >= WORK_CAPACITY:
                raise StorageUnavailableError("Recovery queue is full")
            with suppress(*DRIVER_ERRORS):
                page = await self.session.execute(
                    conditional_write(
                        "BEGIN BATCH UPDATE work_rows SET revision=%s, pending_count=%s "
                        "WHERE kind=%s AND shard=%s AND row_key='head' IF revision=%s; "
                        "INSERT INTO work_rows (kind, shard, row_key, payload) "
                        "VALUES (%s, %s, %s, %s) IF NOT EXISTS; APPLY BATCH"
                    ),
                    (
                        head.revision + 1,
                        head.pending_count + 1,
                        self.kind,
                        shard,
                        head.revision,
                        self.kind,
                        shard,
                        "task:" + key,
                        payload,
                    ),
                )
                if page.was_applied:
                    return
        raise StorageUnavailableError("Recovery admission outcome is unknown")

    async def remove(self, key: str, payload: str) -> None:
        shard = self.shard(key)
        for _ in range(MAX_ATTEMPTS):
            head = await self._head(shard)
            existing = await self._item(shard, key)
            if existing is None:
                return
            if existing != payload:
                raise StorageUnavailableError("Recovery task changed")
            page = await self.session.execute(
                conditional_write(
                    "BEGIN BATCH UPDATE work_rows SET revision=%s, pending_count=%s "
                    "WHERE kind=%s AND shard=%s AND row_key='head' IF revision=%s; "
                    "DELETE FROM work_rows WHERE kind=%s AND shard=%s AND row_key=%s "
                    "IF payload=%s; APPLY BATCH"
                ),
                (
                    head.revision + 1,
                    head.pending_count - 1,
                    self.kind,
                    shard,
                    head.revision,
                    self.kind,
                    shard,
                    "task:" + key,
                    payload,
                ),
            )
            if page.was_applied:
                return
        raise StorageUnavailableError("Recovery completion is busy")

    async def pending(self, *, limit: int) -> tuple[WorkItem, ...]:
        if not 1 <= limit <= WORK_CAPACITY:
            raise ValueError("Recovery batch must be between 1 and the shard capacity")
        items: list[WorkItem] = []
        start = self._next_shard
        self._next_shard = (start + 1) % WORK_SHARDS
        for step in range(WORK_SHARDS):
            shard = (start + step) % WORK_SHARDS
            page = await self.session.execute(
                serial_read(
                    "SELECT row_key, payload FROM work_rows WHERE kind=%s AND shard=%s "
                    "AND row_key >= 'task:' LIMIT %s"
                ),
                (self.kind, shard, limit - len(items)),
            )
            items.extend(
                WorkItem.model_validate(row, from_attributes=True)
                for row in page.current_rows
            )
            if len(items) >= limit:
                break
        return tuple(items)
