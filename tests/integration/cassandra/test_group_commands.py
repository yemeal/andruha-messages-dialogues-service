import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from cassandra import OperationTimedOut

from app.application.commands.groups.add_member.command import AddGroupMemberCommand
from app.application.commands.groups.add_member.handler import AddGroupMemberHandler
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import GroupReadConflictError
from app.application.ports.persistence.models import GroupCreationIntent
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.exceptions.groups import GroupMemberLimitExceededError
from app.domain.value_objects.group_title import GroupTitle
from app.infrastructure.persistence.cassandra.group_commands import (
    CassandraGroupCommands,
)
from app.infrastructure.persistence.cassandra.migrations import (
    SchemaChecksumMismatchError,
    migrate,
)

NOW = datetime(2026, 11, 16, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_cqltrack_status_rollback_and_remigrate_preserve_version_history(
    unmigrated_cassandra_session,
    tmp_path,
):
    from app.infrastructure.persistence.cassandra.migrations import MigrationRunner

    cassandra_session = unmigrated_cassandra_session
    (tmp_path / "V001__migration_probe.cql").write_text(
        "CREATE TABLE canonical_rows (id uuid PRIMARY KEY);\n"
        "-- @down\nDROP TABLE canonical_rows;\n",
        encoding="utf-8",
    )
    runner = MigrationRunner(cassandra_session, tmp_path)
    assert [item.version for item in await runner.migrate()] == [1]
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "applied")
    ]
    record = cassandra_session.execute(
        "SELECT status, checksum FROM cqltrack_history WHERE version=1"
    ).one()
    assert record["status"] == "applied"
    assert record["checksum"]

    assert [item.version for item in await runner.rollback()] == [1]
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "pending")
    ]
    assert (
        cassandra_session.execute(
            "SELECT table_name FROM system_schema.tables "
            "WHERE keyspace_name=%s AND table_name='canonical_rows'",
            (cassandra_session.keyspace,),
        ).one()
        is None
    )

    assert [item.version for item in await runner.migrate()] == [1]
    assert [(item.version, item.status) for item in await runner.status()] == [
        (1, "applied")
    ]


@pytest.mark.asyncio
async def test_parallel_migration_process_cannot_enter_persistent_lock(
    cassandra_session,
):
    from app.infrastructure.persistence.cassandra.migrations import MigrationRunner

    runner = MigrationRunner(cassandra_session)
    environment = os.environ | {
        "PYTHONPATH": "src",
        "CQLTRACK_CONTACT_POINTS": os.environ["MESSAGES_TEST_CASSANDRA_HOST"],
        "CQLTRACK_PORT": os.environ["MESSAGES_TEST_CASSANDRA_PORT"],
        "CQLTRACK_KEYSPACE": cassandra_session.keyspace,
    }
    async with runner.locked():
        lock = cassandra_session.execute(
            "SELECT owner, TTL(owner) AS remaining FROM andruha_schema_lock "
            "WHERE lock_id='schema'"
        ).one()
        assert lock["owner"] is not None
        assert lock["remaining"] is None
        contender = subprocess.run(
            [sys.executable, "-m", "app.entrypoints.migrations", "migrate"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert contender.returncode != 0
        assert "SchemaMigrationBusyError" in contender.stderr
        assert (
            cassandra_session.execute(
                "SELECT owner FROM andruha_schema_lock WHERE lock_id='schema'"
            ).one()["owner"]
            == lock["owner"]
        )

    assert await runner.migrate() == []
    assert (
        cassandra_session.execute(
            "SELECT owner FROM andruha_schema_lock WHERE lock_id='schema'"
        ).one()
        is None
    )


@pytest.mark.asyncio
async def test_cqltrack_diff_reports_real_column_drift(cassandra_session):
    from app.infrastructure.persistence.cassandra.migrations import MigrationRunner

    target = "messages_diff_" + uuid7().hex
    cassandra_session.execute(
        f"CREATE KEYSPACE {target} WITH replication = "
        "{'class': 'SimpleStrategy', 'replication_factor': 1}"
    )
    try:
        peer = cassandra_session.cluster.connect(target)
        await MigrationRunner(peer).migrate()
        runner = MigrationRunner(cassandra_session)
        assert await runner.diff(target) == []
        peer.execute("ALTER TABLE canonical_rows ADD migration_probe text")

        assert [
            (item.kind, item.path, item.change) for item in await runner.diff(target)
        ] == [("column", "canonical_rows.migration_probe", "only_in_target")]
    finally:
        cassandra_session.execute(f"DROP KEYSPACE IF EXISTS {target}")


@pytest.mark.asyncio
async def test_group_creation_replays_saved_identity_after_adapter_restart(
    cassandra_session,
):
    operation_id, owner_id = uuid7(), uuid7()
    intent = GroupCreationIntent(
        actor_id=owner_id,
        title=GroupTitle.from_str("Canonical group"),
        member_ids=frozenset((owner_id,)),
        avatar_object_id=None,
    )
    first = CassandraGroupCommands(cassandra_session)
    group = GroupDialog.create(
        dialog_id=operation_id,
        owner_id=owner_id,
        title=intent.title,
        now=NOW,
    )
    accepted = await first.create_or_get_group(
        group, command_id=operation_id, intent=intent
    )

    restarted = CassandraGroupCommands(cassandra_session)
    later_candidate = GroupDialog.create(
        dialog_id=operation_id,
        owner_id=owner_id,
        title=intent.title,
        now=NOW + timedelta(days=1),
    )
    replay = await restarted.create_or_get_group(
        later_candidate,
        command_id=operation_id,
        intent=intent,
    )
    current = await restarted.get_by_id(operation_id)

    assert replay == accepted
    assert replay.result.created_at == NOW
    assert current.dialog.id == operation_id
    assert current.revision == 1


class RegisteredAccounts:
    async def require_registered(self, user_id):
        pass

    async def require_registered_many(self, user_ids):
        pass


@pytest.mark.asyncio
async def test_concurrent_writers_accept_only_one_last_group_place(cassandra_session):
    operation_id, owner_id = uuid7(), uuid7()
    initial = tuple(uuid7() for _ in range(998))
    group = GroupDialog.create(
        dialog_id=operation_id,
        owner_id=owner_id,
        title="One place left",
        initial_members=initial,
        now=NOW,
    )
    store = CassandraGroupCommands(cassandra_session)
    await store.create_or_get_group(
        group,
        command_id=operation_id,
        intent=GroupCreationIntent(owner_id, group.title, group.members, None),
    )
    handlers = [
        AddGroupMemberHandler(
            groups=CassandraGroupCommands(cassandra_session),
            registered_users=RegisteredAccounts(),
            clock=lambda: NOW + timedelta(seconds=1),
        )
        for _ in range(2)
    ]
    results = await asyncio.gather(
        *(
            handler(
                AddGroupMemberCommand(
                    dialog_id=operation_id,
                    actor_id=owner_id,
                    user_id=uuid7(),
                    command_id=uuid7(),
                )
            )
            for handler in handlers
        ),
        return_exceptions=True,
    )

    assert (
        sum(isinstance(result, GroupMemberLimitExceededError) for result in results)
        == 1
    )
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    current = await store.get_by_id(operation_id)
    assert len(current.dialog.members) == 1000
    assert current.revision == 2


@pytest.mark.asyncio
async def test_unknown_uncommitted_write_is_unavailable_and_stale_absence_is_rejected(
    cassandra_session, monkeypatch
):
    group_id, owner_id, member_id, command_id = (uuid7() for _ in range(4))
    group = GroupDialog.create(
        dialog_id=group_id, owner_id=owner_id, title="Not committed", now=NOW
    )
    store = CassandraGroupCommands(cassandra_session)
    await store.create_or_get_group(
        group,
        command_id=group_id,
        intent=GroupCreationIntent(owner_id, group.title, group.members, None),
    )
    execute = cassandra_session.execute_async

    def lose_write(statement, *args, **kwargs):
        if "BEGIN BATCH" in getattr(statement, "query_string", ""):
            raise OperationTimedOut()
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(cassandra_session, "execute_async", lose_write)
    handler = AddGroupMemberHandler(
        groups=store,
        registered_users=RegisteredAccounts(),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    command = AddGroupMemberCommand(
        dialog_id=group_id,
        actor_id=owner_id,
        user_id=member_id,
        command_id=command_id,
    )
    with pytest.raises(StorageUnavailableError):
        await handler(command)
    assert (await store.get_by_id(group_id)).revision == 1
    assert (
        await store.get_membership_result(group_id, command_id, at_revision=1) is None
    )

    monkeypatch.setattr(cassandra_session, "execute_async", execute)
    accepted = await handler(command)
    with pytest.raises(GroupReadConflictError):
        await store.get_membership_result(group_id, uuid7(), at_revision=1)
    assert (await store.get_by_id(group_id)).revision == 2
    assert member_id in accepted.members


@pytest.mark.asyncio
async def test_full_working_journal_refuses_new_writes_without_discarding_acceptance(
    cassandra_session,
):
    group_id, owner_id = uuid7(), uuid7()
    group = GroupDialog.create(
        dialog_id=group_id, owner_id=owner_id, title="Bounded", now=NOW
    )
    store = CassandraGroupCommands(cassandra_session, max_working_commands=1)
    await store.create_or_get_group(
        group,
        command_id=group_id,
        intent=GroupCreationIntent(owner_id, group.title, group.members, None),
    )
    handler = AddGroupMemberHandler(
        groups=store,
        registered_users=RegisteredAccounts(),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    first_command = AddGroupMemberCommand(
        dialog_id=group_id,
        actor_id=owner_id,
        user_id=uuid7(),
        command_id=uuid7(),
    )
    first = await handler(first_command)
    with pytest.raises(StorageUnavailableError):
        await handler(
            AddGroupMemberCommand(
                dialog_id=group_id,
                actor_id=owner_id,
                user_id=uuid7(),
                command_id=uuid7(),
            )
        )
    assert await handler(first_command) == first
    current = await store.get_by_id(group_id)
    assert len(current.dialog.members) == 2
    assert current.revision == 2


@pytest.mark.asyncio
async def test_migrations_are_repeatable_and_changed_applied_checksum_is_rejected(
    cassandra_session, tmp_path
):
    await migrate(cassandra_session)
    (tmp_path / "V001__canonical_groups.cql").write_text(
        "CREATE TABLE IF NOT EXISTS different_schema (id uuid PRIMARY KEY);",
        encoding="utf-8",
    )
    with pytest.raises(SchemaChecksumMismatchError):
        await migrate(cassandra_session, tmp_path)


@pytest.mark.asyncio
async def test_lost_real_conditional_commit_response_resolves_by_saved_result(
    cassandra_session,
    monkeypatch,
    lost_commit_response,
):
    operation_id, owner_id, member_id, command_id = (uuid7() for _ in range(4))
    group = GroupDialog.create(
        dialog_id=operation_id,
        owner_id=owner_id,
        title="Unknown outcome",
        now=NOW,
    )
    store = CassandraGroupCommands(cassandra_session)
    await store.create_or_get_group(
        group,
        command_id=operation_id,
        intent=GroupCreationIntent(owner_id, group.title, group.members, None),
    )
    execute = cassandra_session.execute_async
    dropped = False

    def drop_committed_response(statement, *args, **kwargs):
        nonlocal dropped
        result = execute(statement, *args, **kwargs)
        if not dropped and "BEGIN BATCH" in getattr(statement, "query_string", ""):
            dropped = True
            return lost_commit_response(result)
        return result

    monkeypatch.setattr(cassandra_session, "execute_async", drop_committed_response)
    handler = AddGroupMemberHandler(
        groups=store,
        registered_users=RegisteredAccounts(),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    command = AddGroupMemberCommand(
        dialog_id=operation_id,
        actor_id=owner_id,
        user_id=member_id,
        command_id=command_id,
    )
    accepted = await handler(command)
    replay = await handler(command)
    current = await store.get_by_id(operation_id)

    assert dropped is True
    assert accepted == replay
    assert set(current.dialog.members) == {owner_id, member_id}
    assert current.revision == 2
