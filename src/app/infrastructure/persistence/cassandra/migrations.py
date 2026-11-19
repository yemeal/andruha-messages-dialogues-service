"""Async CQL migration runner; cql-track supplies file format and checksums."""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid7

from cassandra import ConsistencyLevel
from cassandra.cluster import Session
from cassandra.query import SimpleStatement
from cqltrack.differ import Difference
from cqltrack.exceptions import ChecksumMismatch
from cqltrack.parser import Migration, parse_filename, scan_directory
from pydantic import BaseModel, Field, field_validator

from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.migration_schema import (
    MigrationSession,
    validate_keyspace,
)
from app.infrastructure.persistence.cassandra.migration_schema import (
    SchemaAgreementError as SchemaAgreementError,
)
from app.infrastructure.persistence.cassandra.statements import (
    DRIVER_ERRORS,
    conditional_write,
    serial_read,
)

SCHEMA = Path(__file__).with_name("schema")
GUARD_TABLE = "andruha_schema_lock"
MAX_MIGRATIONS = 1000
SchemaChecksumMismatchError = ChecksumMismatch
logger = logging.getLogger(__name__)
type RecordStatus = Literal[
    "applying", "applied", "failed", "rolling_back", "rollback_failed"
]


class SchemaMigrationBusyError(RuntimeError):
    """Another job owns the persistent migration lock."""


class MigrationRecoveryRequiredError(RuntimeError):
    """An interrupted migration requires inspection and explicit resume."""


class MigrationStateUnknownError(RuntimeError):
    """A tracking or lock write could not be confirmed."""


@dataclass(frozen=True)
class MigrationStatus:
    version: int
    description: str
    status: str


class MigrationHistoryRecord(BaseModel):
    version: int = Field(ge=1)
    description: str
    checksum: str
    status: RecordStatus
    applied_at: datetime
    applied_by: str
    exec_time_ms: int = Field(ge=0)

    @field_validator("applied_at", mode="after")
    @classmethod
    def native_timestamp_is_utc(cls, value: datetime) -> datetime:
        # Cassandra timestamps are UTC instants; the native driver returns them naive.
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )


class _LockOwner(BaseModel):
    owner: UUID


class MigrationRunner:
    def __init__(
        self,
        session: Session | AsyncCassandraSession,
        schema_path: Path = SCHEMA,
        *,
        agreement_seconds: float = 30,
    ) -> None:
        self._db = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )
        if not self._db.keyspace:
            raise ValueError("Connect to an existing keyspace before migrating")
        self._keyspace = validate_keyspace(self._db.keyspace)
        if not schema_path.is_dir():
            raise ValueError("Migration directory is unavailable")
        paths = tuple(schema_path.glob("*.cql"))
        if not paths or len(paths) > MAX_MIGRATIONS:
            raise ValueError("Migration directory must contain 1..1000 CQL files")
        for path in paths:
            parse_filename(path.name)
        self._migrations = scan_directory(schema_path)
        self._session = MigrationSession(self._db, agreement_seconds=agreement_seconds)

    async def _owner(self) -> UUID | None:
        page = await self._db.execute(
            serial_read(f"SELECT owner FROM {GUARD_TABLE} WHERE lock_id='schema'")
        )
        row = page.one()
        return (
            _LockOwner.model_validate(row, from_attributes=True).owner
            if row is not None
            else None
        )

    async def _release(self, owner: UUID) -> None:
        try:
            result = await self._db.execute(
                conditional_write(
                    f"DELETE FROM {GUARD_TABLE} WHERE lock_id='schema' IF owner=%s"
                ),
                (owner,),
            )
            if result.was_applied:
                return
        except DRIVER_ERRORS:
            pass
        if await self._owner() == owner:
            raise MigrationStateUnknownError("Schema lock release was not confirmed")

    @asynccontextmanager
    async def locked(self) -> AsyncIterator[UUID]:
        await self._session.execute(
            f"CREATE TABLE IF NOT EXISTS {GUARD_TABLE} (lock_id text PRIMARY KEY, owner uuid)"
        )
        owner = uuid7()
        try:
            result = await self._db.execute(
                conditional_write(
                    f"INSERT INTO {GUARD_TABLE} (lock_id, owner) VALUES ('schema', %s) IF NOT EXISTS USING TTL 0"
                ),
                (owner,),
            )
            if not result.was_applied:
                raise SchemaMigrationBusyError("Schema migration lock is already held")
        except DRIVER_ERRORS as error:
            if await self._owner() != owner:
                raise MigrationStateUnknownError(
                    "Schema lock acquisition was not confirmed"
                ) from error
        failure = None
        try:
            yield owner
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                await self._release(owner)
            except BaseException:
                if failure is None:
                    raise
                failure.add_note(
                    "Schema lock cleanup was not confirmed; inspect its owner before retrying"
                )

    async def _initialize_history(self) -> None:
        await self._session.execute(
            "CREATE TABLE IF NOT EXISTS cqltrack_history (version int PRIMARY KEY, "
            "description text, checksum text, status text, applied_at timestamp, "
            "applied_by text, exec_time_ms int)"
        )

    async def history(self) -> tuple[MigrationHistoryRecord, ...]:
        exists = await self._session.execute(
            "SELECT table_name FROM system_schema.tables "
            "WHERE keyspace_name=%s AND table_name='cqltrack_history'",
            (self._keyspace,),
        )
        if exists.one() is None:
            return ()
        rows = await self._db.fetch_all(
            SimpleStatement(
                "SELECT version, description, checksum, status, applied_at, applied_by, exec_time_ms "
                "FROM cqltrack_history LIMIT 1001",
                consistency_level=ConsistencyLevel.QUORUM,
                fetch_size=100,
            ),
            max_rows=MAX_MIGRATIONS,
        )
        return tuple(
            sorted(
                (
                    MigrationHistoryRecord.model_validate(row, from_attributes=True)
                    for row in rows
                ),
                key=lambda item: item.version,
            )
        )

    async def _record(self, version: int) -> MigrationHistoryRecord | None:
        result = await self._db.execute(
            serial_read(
                "SELECT version, description, checksum, status, applied_at, applied_by, exec_time_ms "
                "FROM cqltrack_history WHERE version=%s"
            ),
            (version,),
        )
        row = result.one()
        return (
            MigrationHistoryRecord.model_validate(row, from_attributes=True)
            if row is not None
            else None
        )

    def _validate(self, records: tuple[MigrationHistoryRecord, ...]) -> None:
        files = {item.version: item for item in self._migrations}
        if any(
            item.version not in files or item.checksum != files[item.version].checksum
            for item in records
        ):
            raise SchemaChecksumMismatchError(
                "An applied migration is missing or was modified"
            )

    async def status(self) -> tuple[MigrationStatus, ...]:
        records = await self.history()
        self._validate(records)
        by_version = {item.version: item for item in records}
        return tuple(
            MigrationStatus(
                item.version,
                item.description,
                by_version[item.version].status
                if item.version in by_version
                else "pending",
            )
            for item in self._migrations
        )

    async def _save(
        self, record: MigrationHistoryRecord, expected: MigrationHistoryRecord | None
    ) -> None:
        values = (
            record.description,
            record.checksum,
            record.status,
            record.applied_at,
            record.applied_by,
            record.exec_time_ms,
            record.version,
        )
        if expected is None:
            query = (
                "INSERT INTO cqltrack_history (description, checksum, status, applied_at, applied_by, exec_time_ms, version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) IF NOT EXISTS"
            )
        else:
            query = (
                "UPDATE cqltrack_history SET description=%s, checksum=%s, status=%s, applied_at=%s, applied_by=%s, exec_time_ms=%s "
                "WHERE version=%s IF checksum=%s AND status=%s AND applied_by=%s"
            )
            values += (expected.checksum, expected.status, expected.applied_by)
        try:
            result = await self._db.execute(conditional_write(query), values)
            if result.was_applied:
                return
        except DRIVER_ERRORS:
            pass
        stored = await self._record(record.version)
        if stored is None or (
            stored.checksum,
            stored.status,
            stored.applied_by,
            stored.exec_time_ms,
        ) != (
            record.checksum,
            record.status,
            record.applied_by,
            record.exec_time_ms,
        ):
            raise MigrationStateUnknownError(
                "Migration tracking write was not confirmed"
            )

    @staticmethod
    def _new_record(
        migration: Migration, owner: UUID, status: RecordStatus, elapsed: int = 0
    ) -> MigrationHistoryRecord:
        return MigrationHistoryRecord(
            version=migration.version,
            description=migration.description,
            checksum=migration.checksum,
            status=status,
            applied_at=datetime.now(UTC),
            applied_by=str(owner),
            exec_time_ms=elapsed,
        )

    async def _apply(
        self,
        migration: Migration,
        owner: UUID,
        previous: MigrationHistoryRecord | None,
        *,
        down: bool,
    ) -> None:
        state = self._new_record(
            migration, owner, "rolling_back" if down else "applying"
        )
        await self._save(state, previous)
        started = time.monotonic()
        try:
            for statement in (
                migration.down_statements if down else migration.up_statements
            ):
                await self._session.execute(statement)
            if down:
                await self._delete(state)
            else:
                await self._save(
                    self._new_record(
                        migration,
                        owner,
                        "applied",
                        int((time.monotonic() - started) * 1000),
                    ),
                    state,
                )
        except BaseException as error:
            try:
                await self._save(
                    self._new_record(
                        migration,
                        owner,
                        "rollback_failed" if down else "failed",
                        int((time.monotonic() - started) * 1000),
                    ),
                    state,
                )
            except BaseException:
                error.add_note(
                    "Failure tracking was not confirmed; inspect migration history before resume"
                )
            raise
        logger.info(
            "migration_completed version=%s direction=%s",
            migration.version,
            "down" if down else "up",
        )

    async def _delete(self, expected: MigrationHistoryRecord) -> None:
        try:
            result = await self._db.execute(
                conditional_write(
                    "DELETE FROM cqltrack_history WHERE version=%s IF checksum=%s AND status=%s AND applied_by=%s"
                ),
                (
                    expected.version,
                    expected.checksum,
                    expected.status,
                    expected.applied_by,
                ),
            )
            if result.was_applied:
                return
        except DRIVER_ERRORS:
            pass
        if await self._record(expected.version) is not None:
            raise MigrationStateUnknownError(
                "Rollback tracking removal was not confirmed"
            )

    async def migrate(self, *, resume: bool = False) -> list[Migration]:
        async with self.locked() as owner:
            await self._initialize_history()
            records = await self.history()
            self._validate(records)
            if any(
                item.status in {"rolling_back", "rollback_failed"} for item in records
            ):
                raise MigrationRecoveryRequiredError(
                    "Use rollback --resume after inspecting interrupted rollback"
                )
            if not resume and any(item.status != "applied" for item in records):
                raise MigrationRecoveryRequiredError(
                    "Inspect the partial migration, then explicitly use migrate --resume"
                )
            by_version = {item.version: item for item in records}
            highest = max(
                (item.version for item in records if item.status == "applied"),
                default=0,
            )
            pending = [
                item
                for item in self._migrations
                if item.version not in by_version
                or by_version[item.version].status != "applied"
            ]
            if any(item.version < highest for item in pending):
                raise ValueError(
                    "New migrations must follow all already applied versions"
                )
            for item in pending:
                await self._apply(item, owner, by_version.get(item.version), down=False)
            return pending

    async def rollback(
        self, steps: int = 1, *, resume: bool = False
    ) -> list[Migration]:
        if steps < 1:
            raise ValueError("Rollback steps must be positive")
        async with self.locked() as owner:
            records = await self.history()
            self._validate(records)
            if any(item.status in {"applying", "failed"} for item in records):
                raise MigrationRecoveryRequiredError(
                    "Resolve interrupted upgrade before rollback"
                )
            if not resume and any(item.status != "applied" for item in records):
                raise MigrationRecoveryRequiredError(
                    "Inspect the partial rollback, then explicitly use rollback --resume"
                )
            targets = sorted(records, key=lambda item: item.version, reverse=True)[
                :steps
            ]
            files = {item.version: item for item in self._migrations}
            if any(not files[item.version].down_statements for item in targets):
                raise ValueError("Rollback requires an explicit -- @down section")
            for record in targets:
                await self._apply(files[record.version], owner, record, down=True)
            return [files[item.version] for item in targets]

    async def diff(self, target_keyspace: str) -> list[Difference]:
        return await self._session.diff(
            self._keyspace, validate_keyspace(target_keyspace)
        )


async def migrate(
    session: Session | AsyncCassandraSession, schema_path: Path = SCHEMA
) -> None:
    await MigrationRunner(session, schema_path).migrate()
