import pytest
from cassandra import OperationTimedOut

from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.migrations import (
    MigrationRecoveryRequiredError,
    MigrationRunner,
)


@pytest.mark.asyncio
async def test_migration_queries_and_history_never_call_synchronous_native_api(
    unmigrated_cassandra_session,
    tmp_path,
    monkeypatch,
):
    native = unmigrated_cassandra_session
    (tmp_path / "V001__async_probe.cql").write_text(
        "CREATE TABLE async_probe (id uuid PRIMARY KEY);\n"
        "-- @down\nDROP TABLE async_probe;\n",
        encoding="utf-8",
    )

    def synchronous_query_is_forbidden(*args, **kwargs):
        raise AssertionError("Migration CQL must use execute_async")

    monkeypatch.setattr(native, "execute", synchronous_query_is_forbidden)
    runner = MigrationRunner(native, tmp_path)
    assert [item.version for item in await runner.migrate()] == [1]
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "applied")
    ]
    history = await runner.history()
    assert [(item.version, item.status) for item in history] == [(1, "applied")]
    assert history[0].checksum
    assert [item.version for item in await runner.rollback()] == [1]
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "pending")
    ]
    page = await AsyncCassandraSession(native).execute(
        "SELECT table_name FROM system_schema.tables "
        "WHERE keyspace_name=%s AND table_name='async_probe'",
        (native.keyspace,),
    )
    assert page.one() is None


@pytest.mark.asyncio
async def test_partial_upgrade_is_not_retried_without_explicit_resume(
    unmigrated_cassandra_session,
    tmp_path,
    monkeypatch,
):
    native = unmigrated_cassandra_session
    (tmp_path / "V001__partial.cql").write_text(
        "CREATE TABLE IF NOT EXISTS partial_probe (id uuid PRIMARY KEY);\n"
        "ALTER TABLE partial_probe ADD content text;\n",
        encoding="utf-8",
    )
    (tmp_path / "V002__later.cql").write_text(
        "CREATE TABLE IF NOT EXISTS later_probe (id uuid PRIMARY KEY);",
        encoding="utf-8",
    )
    original = native.execute_async
    attempts = 0

    def fail_alter(statement, *args, **kwargs):
        nonlocal attempts
        if "ALTER TABLE partial_probe" in getattr(statement, "query_string", ""):
            attempts += 1
            raise OperationTimedOut()
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(native, "execute_async", fail_alter)
    runner = MigrationRunner(native, tmp_path)
    with pytest.raises(OperationTimedOut):
        await runner.migrate()
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "failed"),
        (2, "pending"),
    ]
    with pytest.raises(MigrationRecoveryRequiredError):
        await runner.migrate()
    assert attempts == 1
    monkeypatch.setattr(native, "execute_async", original)
    assert [item.version for item in await runner.migrate(resume=True)] == [1, 2]
    assert [(item.version, item.status) for item in await runner.history()] == [
        (1, "applied"),
        (2, "applied"),
    ]


@pytest.mark.asyncio
async def test_partial_rollback_is_recorded_and_requires_explicit_resume(
    unmigrated_cassandra_session,
    tmp_path,
    monkeypatch,
):
    native = unmigrated_cassandra_session
    (tmp_path / "V001__rollback.cql").write_text(
        "CREATE TABLE IF NOT EXISTS rollback_a (id uuid PRIMARY KEY);\n"
        "CREATE TABLE IF NOT EXISTS rollback_b (id uuid PRIMARY KEY);\n"
        "-- @down\nDROP TABLE IF EXISTS rollback_b;\nDROP TABLE IF EXISTS rollback_a;\n",
        encoding="utf-8",
    )
    runner = MigrationRunner(native, tmp_path)
    await runner.migrate()
    original = native.execute_async

    def fail_last_drop(statement, *args, **kwargs):
        if "DROP TABLE IF EXISTS rollback_a" in getattr(statement, "query_string", ""):
            raise OperationTimedOut()
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(native, "execute_async", fail_last_drop)
    with pytest.raises(OperationTimedOut):
        await runner.rollback()
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "rollback_failed")
    ]
    with pytest.raises(MigrationRecoveryRequiredError):
        await runner.rollback()
    monkeypatch.setattr(native, "execute_async", original)
    assert [item.version for item in await runner.rollback(resume=True)] == [1]
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "pending")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary", ["history-insert", "history-applied", "lock-acquire", "lock-release"]
)
async def test_lost_tracking_response_is_resolved_from_durable_state(
    unmigrated_cassandra_session,
    tmp_path,
    monkeypatch,
    lost_commit_response,
    boundary,
):
    native = unmigrated_cassandra_session
    (tmp_path / "V001__tracking.cql").write_text(
        "CREATE TABLE IF NOT EXISTS tracking_probe (id uuid PRIMARY KEY);",
        encoding="utf-8",
    )
    original = native.execute_async
    dropped = False

    def lose_once(statement, parameters=None, **kwargs):
        nonlocal dropped
        query = getattr(statement, "query_string", "")
        match = (
            (
                boundary == "history-insert"
                and query.startswith("INSERT INTO cqltrack_history")
            )
            or (
                boundary == "history-applied"
                and query.startswith("UPDATE cqltrack_history")
                and parameters[2] == "applied"
            )
            or (
                boundary == "lock-acquire"
                and query.startswith("INSERT INTO andruha_schema_lock")
            )
            or (
                boundary == "lock-release"
                and query.startswith("DELETE FROM andruha_schema_lock")
            )
        )
        result = original(statement, parameters, **kwargs)
        if match and not dropped:
            dropped = True
            return lost_commit_response(result)
        return result

    monkeypatch.setattr(native, "execute_async", lose_once)
    runner = MigrationRunner(native, tmp_path)
    assert [item.version for item in await runner.migrate()] == [1]
    assert dropped is True
    assert [(item.version, item.status) for item in await runner.history()] == [
        (1, "applied")
    ]
    assert await runner.migrate() == []
