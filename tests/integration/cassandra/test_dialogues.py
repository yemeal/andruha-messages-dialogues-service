import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from cassandra import OperationTimedOut

from app.application.exceptions.dependencies import StorageUnavailableError
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.direct_participants import DirectParticipants
from app.infrastructure.persistence.cassandra.dialogues import CassandraSavedDialogs

NOW = datetime(2026, 11, 16, 2, tzinfo=UTC)


@pytest.mark.asyncio
async def test_runtime_dialog_creation_does_not_call_synchronous_query_api(
    cassandra_session,
    monkeypatch,
):
    from app.infrastructure.persistence.cassandra.dialogues import (
        CassandraDirectDialogs,
    )

    def synchronous_query_is_forbidden(*args, **kwargs):
        raise AssertionError("Runtime must use execute_async, not Session.execute")

    monkeypatch.setattr(cassandra_session, "execute", synchronous_query_is_forbidden)
    candidate = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(uuid7(), uuid7()), now=NOW
    )
    store = CassandraDirectDialogs(cassandra_session)
    accepted = await store.create_or_get(candidate)
    assert accepted.dialog == candidate
    assert await store.get_by_id(candidate.id) == candidate
    assert await store.get_by_participants(candidate.participants) == candidate


@pytest.mark.asyncio
async def test_concurrent_saved_creation_keeps_one_owner_identity_after_restart(
    cassandra_session,
):
    owner = uuid7()
    candidates = tuple(
        SavedDialog.create(
            user_id=owner, dialog_id=uuid7(), now=NOW + timedelta(seconds=index)
        )
        for index in range(32)
    )
    results = await asyncio.gather(
        *(
            CassandraSavedDialogs(cassandra_session).create_or_get(candidate)
            for candidate in candidates
        )
    )
    winner = results[0].dialog
    assert winner in candidates
    assert all(result.dialog == winner for result in results)
    assert sum(result.created for result in results) == 1
    restarted = CassandraSavedDialogs(cassandra_session)
    assert await restarted.get_by_owner(owner) == winner
    assert await restarted.get_by_id(winner.id) == winner
    assert await restarted.get_by_owner(uuid7()) is None


@pytest.mark.asyncio
async def test_reverse_pair_concurrent_creations_return_one_durable_winner(
    cassandra_session,
):
    from app.infrastructure.persistence.cassandra.dialogues import (
        CassandraDirectDialogs,
    )

    alice, bob = uuid7(), uuid7()
    candidates = tuple(
        DirectDialog.create(
            participants=DirectParticipants.from_user_ids(*pair),
            dialog_id=uuid7(),
            now=NOW + timedelta(seconds=index),
        )
        for index, pair in enumerate(((alice, bob), (bob, alice)))
    )
    results = await asyncio.gather(
        *(
            CassandraDirectDialogs(cassandra_session).create_or_get(candidate)
            for candidate in candidates
        )
    )
    assert results[0].dialog == results[1].dialog
    assert sum(result.created for result in results) == 1
    winner = results[0].dialog
    assert winner in candidates

    restarted = CassandraDirectDialogs(cassandra_session)
    assert await restarted.get_by_id(winner.id) == winner
    assert (
        await restarted.get_by_participants(
            DirectParticipants.from_user_ids(bob, alice)
        )
        == winner
    )
    loser = next(candidate for candidate in candidates if candidate.id != winner.id)
    assert await restarted.get_by_id(loser.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boundary", "after_commit", "first_fails", "original_wins"),
    [
        ("dialog_creations", False, True, False),
        ("dialog_creations", True, False, True),
        ("canonical_rows", False, True, True),
        ("canonical_rows", True, False, True),
    ],
    ids=[
        "before-reservation",
        "lost-reservation-response",
        "before-head",
        "lost-head-response",
    ],
)
async def test_unknown_creation_outcome_never_returns_unconfirmed_success(
    cassandra_session,
    monkeypatch,
    lost_commit_response,
    boundary,
    after_commit,
    first_fails,
    original_wins,
):
    from app.infrastructure.persistence.cassandra.dialogues import (
        CassandraDirectDialogs,
    )

    pair = DirectParticipants.from_user_ids(uuid7(), uuid7())
    original = DirectDialog.create(participants=pair, dialog_id=uuid7(), now=NOW)
    execute = cassandra_session.execute_async
    dropped = False

    def fail_once(statement, *args, **kwargs):
        nonlocal dropped
        if not dropped and f"INSERT INTO {boundary} " in getattr(
            statement, "query_string", ""
        ):
            dropped = True
            if after_commit:
                return lost_commit_response(execute(statement, *args, **kwargs))
            raise OperationTimedOut()
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(cassandra_session, "execute_async", fail_once)
    store = CassandraDirectDialogs(cassandra_session)
    if first_fails:
        with pytest.raises(StorageUnavailableError):
            await store.create_or_get(original)
    else:
        assert (await store.create_or_get(original)).dialog == original
    assert dropped is True

    later = DirectDialog.create(
        participants=pair, dialog_id=uuid7(), now=NOW + timedelta(days=1)
    )
    restarted = CassandraDirectDialogs(cassandra_session)
    replay = await restarted.create_or_get(later)
    expected = original if original_wins else later
    assert replay.dialog == expected
    assert await restarted.get_by_id(expected.id) == expected
    assert await restarted.get_by_participants(pair) == expected


@pytest.mark.asyncio
async def test_typed_dialog_repositories_never_return_another_dialog_kind(
    cassandra_session,
):
    from app.application.exceptions.groups import GroupCreationConflictError
    from app.infrastructure.persistence.cassandra.dialogues import (
        CassandraDirectDialogs,
    )
    from app.infrastructure.persistence.cassandra.group_commands import (
        CassandraGroupCommands,
    )

    owner, peer = uuid7(), uuid7()
    direct = (
        await CassandraDirectDialogs(cassandra_session).create_or_get(
            DirectDialog.create(
                participants=DirectParticipants.from_user_ids(owner, peer), now=NOW
            )
        )
    ).dialog
    saved = (
        await CassandraSavedDialogs(cassandra_session).create_or_get(
            SavedDialog.create(user_id=owner, now=NOW)
        )
    ).dialog

    assert await CassandraDirectDialogs(cassandra_session).get_by_id(saved.id) is None
    assert await CassandraSavedDialogs(cassandra_session).get_by_id(direct.id) is None
    groups = CassandraGroupCommands(cassandra_session)
    assert await groups.get_by_id(direct.id) is None
    assert await groups.get_by_id(saved.id) is None
    with pytest.raises(GroupCreationConflictError):
        await groups.get_creation_result(direct.id)
