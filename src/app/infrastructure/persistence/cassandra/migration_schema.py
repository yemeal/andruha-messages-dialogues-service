"""Asynchronous schema agreement and bounded, fresh system-schema inspection."""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from cassandra import ConsistencyLevel
from cassandra.query import SimpleStatement
from cqltrack.differ import Difference
from pydantic import BaseModel

from app.infrastructure.persistence.cassandra.async_session import (
    AsyncCassandraSession,
    QueryPage,
)

INTERNAL_TABLES = frozenset(
    {"andruha_schema_lock", "cqltrack_history", "cqltrack_lock"}
)


class SchemaAgreementError(RuntimeError):
    """Schema convergence was not confirmed before the next DDL statement."""


def validate_keyspace(name: object) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
        raise ValueError(
            "Keyspace must be a lowercase CQL identifier of at most 48 characters"
        )
    return name


class _SchemaVersion(BaseModel):
    schema_version: UUID | None


class _Column(BaseModel):
    table_name: str
    column_name: str
    kind: str
    position: int
    clustering_order: str
    type: str


class _Table(BaseModel):
    table_name: str
    default_time_to_live: int
    gc_grace_seconds: int
    compaction: dict[str, str]
    compression: dict[str, str]


class _Index(BaseModel):
    table_name: str
    index_name: str
    kind: str
    options: dict[str, str]


class _UserType(BaseModel):
    type_name: str
    field_names: tuple[str, ...]
    field_types: tuple[str, ...]


class MigrationSession:
    def __init__(
        self,
        session: AsyncCassandraSession,
        *,
        agreement_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
        pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if agreement_seconds <= 0:
            raise ValueError("Schema agreement timeout must be positive")
        self.session = session
        self.agreement_seconds = agreement_seconds
        self._clock = clock
        self._pause = pause

    async def execute(
        self, query: str, parameters: Sequence[object] | None = None
    ) -> QueryPage:
        result = await self.session.execute(
            SimpleStatement(
                query,
                consistency_level=ConsistencyLevel.QUORUM,
                serial_consistency_level=ConsistencyLevel.SERIAL,
            ),
            parameters,
        )
        if query.split(maxsplit=1)[0].upper() in {
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
        }:
            await self.wait_for_schema_agreement()
        return result

    async def wait_for_schema_agreement(self) -> UUID:
        deadline = self._clock() + self.agreement_seconds
        while self._clock() < deadline:
            hosts = self.session.live_hosts
            versions: set[UUID] = set()
            for host in hosts:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise SchemaAgreementError("Schema agreement timed out")
                result = await self.session.execute(
                    SimpleStatement(
                        "SELECT schema_version FROM system.local",
                        consistency_level=ConsistencyLevel.ONE,
                    ),
                    timeout=min(5, remaining),
                    host=host,
                )
                row = result.one()
                if row is None:
                    break
                version = _SchemaVersion.model_validate(
                    row, from_attributes=True
                ).schema_version
                if version is None:
                    break
                versions.add(version)
            else:
                if hosts and len(versions) == 1:
                    return next(iter(versions))
            await self._pause(min(0.1, max(0, deadline - self._clock())))
        raise SchemaAgreementError("Schema agreement timed out")

    async def _metadata(self, query: str, keyspace: str) -> tuple[object, ...]:
        return await self.session.fetch_all(
            SimpleStatement(
                query, consistency_level=ConsistencyLevel.QUORUM, fetch_size=100
            ),
            (validate_keyspace(keyspace),),
            max_rows=10000,
        )

    async def snapshot(self, keyspace: str) -> dict[tuple[str, str], str]:
        exists = await self._metadata(
            "SELECT keyspace_name FROM system_schema.keyspaces WHERE keyspace_name=%s",
            keyspace,
        )
        if not exists:
            raise ValueError("Schema diff keyspace does not exist")
        result: dict[tuple[str, str], str] = {}
        tables = await self._metadata(
            "SELECT table_name, default_time_to_live, gc_grace_seconds, compaction, compression "
            "FROM system_schema.tables WHERE keyspace_name=%s",
            keyspace,
        )
        for raw in tables:
            table = _Table.model_validate(raw, from_attributes=True)
            if table.table_name not in INTERNAL_TABLES:
                result[("table", table.table_name)] = json.dumps(
                    table.model_dump(), sort_keys=True
                )
        columns = await self._metadata(
            "SELECT table_name, column_name, kind, position, clustering_order, type "
            "FROM system_schema.columns WHERE keyspace_name=%s",
            keyspace,
        )
        for raw in columns:
            column = _Column.model_validate(raw, from_attributes=True)
            if column.table_name not in INTERNAL_TABLES:
                result[("column", f"{column.table_name}.{column.column_name}")] = (
                    json.dumps(column.model_dump(), sort_keys=True)
                )
        for raw in await self._metadata(
            "SELECT table_name, index_name, kind, options FROM system_schema.indexes WHERE keyspace_name=%s",
            keyspace,
        ):
            index = _Index.model_validate(raw, from_attributes=True)
            if index.table_name not in INTERNAL_TABLES:
                result[("index", f"{index.table_name}.{index.index_name}")] = (
                    json.dumps(index.model_dump(), sort_keys=True)
                )
        for raw in await self._metadata(
            "SELECT type_name, field_names, field_types FROM system_schema.types WHERE keyspace_name=%s",
            keyspace,
        ):
            user_type = _UserType.model_validate(raw, from_attributes=True)
            result[("udt", user_type.type_name)] = json.dumps(
                user_type.model_dump(), sort_keys=True
            )
        return result

    async def diff(self, source: str, target: str) -> list[Difference]:
        before = await self.wait_for_schema_agreement()
        left, right = await self.snapshot(source), await self.snapshot(target)
        if await self.wait_for_schema_agreement() != before:
            raise SchemaAgreementError("Schema changed during diff; retry the read")
        differences = []
        for kind, path in sorted(left.keys() | right.keys()):
            key = (kind, path)
            if left.get(key) == right.get(key):
                continue
            change = (
                "only_in_source"
                if key not in right
                else "only_in_target"
                if key not in left
                else "differs"
            )
            differences.append(
                Difference(
                    kind,
                    path,
                    change,
                    left.get(key, "missing"),
                    right.get(key, "missing"),
                )
            )
        return differences
