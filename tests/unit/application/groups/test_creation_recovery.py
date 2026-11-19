from uuid import uuid7

import pytest

from app.application.commands.groups.create_group.command import (
    CreateGroupDialogCommand,
)
from app.application.commands.groups.create_group.handler import (
    CreateGroupDialogHandler,
)
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.dialogues import DialogProjectionsIncompleteError
from app.application.exceptions.groups import GroupCreationConflictError


@pytest.mark.asyncio
async def test_retry_after_projection_failure_returns_one_canonical_group(
    group_creation_repo,
    group_projections,
    registered_users,
    make_attachments,
    clock,
    alice_id,
    bob_id,
):
    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=make_attachments(),
        clock=clock.now,
    )
    command = CreateGroupDialogCommand(
        command_id=uuid7(),
        actor_id=alice_id,
        title="Recovery",
        initial_member_ids=(bob_id,),
    )
    group_projections.failing_user_id = bob_id
    with pytest.raises(DialogProjectionsIncompleteError):
        await handler(command)
    assert len(group_creation_repo.groups) == 1
    group_projections.failing_user_id = None
    registered_users.users = frozenset()

    recovered = await handler(command)
    replay = await handler(command)

    assert recovered == replay
    assert recovered.dialog.id == command.command_id
    assert len(group_creation_repo.groups) == 1
    assert len(group_projections.for_user(alice_id)) == 1
    assert len(group_projections.for_user(bob_id)) == 1


@pytest.mark.asyncio
async def test_lost_create_commit_response_replays_saved_result(
    group_creation_repo,
    group_projections,
    registered_users,
    make_attachments,
    clock,
    alice_id,
):
    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=make_attachments(),
        clock=clock.now,
    )
    command = CreateGroupDialogCommand(
        command_id=uuid7(),
        actor_id=alice_id,
        title="Lost response",
    )
    group_creation_repo.lose_create_response = True
    with pytest.raises(StorageUnavailableError):
        await handler(command)

    recovered = await handler(command)

    assert recovered.dialog.id == command.command_id
    assert recovered.dialog.created_at == clock.now()
    assert len(group_creation_repo.groups) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["actor", "title", "members", "avatar"])
async def test_create_operation_rejects_another_intent(
    group_creation_repo,
    group_projections,
    registered_users,
    make_attachments,
    clock,
    alice_id,
    bob_id,
    changed,
):
    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=make_attachments(),
        clock=clock.now,
    )
    command = CreateGroupDialogCommand(
        command_id=uuid7(),
        actor_id=alice_id,
        title="Original",
    )
    accepted = await handler(command)
    changes = {
        "actor": {"actor_id": bob_id},
        "title": {"title": "Other"},
        "members": {"initial_member_ids": (bob_id,)},
        "avatar": {"avatar_object_id": uuid7()},
    }[changed]
    conflicting = CreateGroupDialogCommand(**(command.model_dump() | changes))
    with pytest.raises(GroupCreationConflictError):
        await handler(conflicting)
    assert len(group_creation_repo.groups) == 1
    assert (await handler(command)) == accepted


@pytest.mark.asyncio
async def test_creation_repair_does_not_restore_removed_member_or_old_group_state(
    group_creation_repo,
    group_projections,
    registered_users,
    make_attachments,
    clock,
    alice_id,
    bob_id,
):
    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=make_attachments(),
        clock=clock.now,
    )
    command = CreateGroupDialogCommand(
        command_id=uuid7(),
        actor_id=alice_id,
        title="Original",
        initial_member_ids=(bob_id,),
    )
    group_projections.failing_user_id = bob_id
    with pytest.raises(DialogProjectionsIncompleteError):
        await handler(command)
    group = group_creation_repo.groups[command.command_id]
    group.remove_member(actor_id=alice_id, user_id=bob_id, now=clock.now())
    group_projections.failing_user_id = None

    replay = await handler(command)

    assert replay.dialog.members == tuple(sorted((alice_id, bob_id)))
    assert group.members == frozenset((alice_id,))
    assert group_projections.for_user(bob_id) == ()
