from uuid import UUID

import pytest

from app.application.commands.groups.create_group.command import (
    CreateGroupDialogCommand,
)
from app.application.commands.groups.create_group.handler import (
    CreateGroupDialogHandler,
)
from app.application.commands.groups.create_group.result import CreateGroupDialogResult
from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.dependencies import (
    StorageUnavailableError,
)
from app.application.exceptions.dialogues import (
    DialogProjectionsIncompleteError,
    UserNotRegisteredError,
)
from app.domain.exceptions.groups import (
    GroupMemberLimitExceededError,
    InvalidGroupTitleError,
)
from app.domain.limits import MAX_GROUP_MEMBERS


@pytest.mark.asyncio
async def test_create_group_dialog_success(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
    bob_id: UUID,
    charlie_id: UUID,
) -> None:
    registered_users.users |= {alice_id, bob_id, charlie_id}
    attachments = make_attachments()

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=attachments,
        clock=clock.now,
        ids=ids.new_id,
    )

    command = CreateGroupDialogCommand(
        actor_id=alice_id,
        title="Команда Проекта",
        initial_member_ids=(bob_id, charlie_id),
    )

    result = await handler(command)

    assert isinstance(result, CreateGroupDialogResult)
    assert isinstance(result.dialog, GroupDialogDTO)
    assert result.dialog.title == "Команда Проекта"
    assert result.dialog.owner_id == alice_id
    assert set(result.dialog.members) == {alice_id, bob_id, charlie_id}
    assert result.dialog.version == 1
    assert result.dialog.created_at == clock.now()
    assert result.dialog.avatar_object_id is None

    # Check persistence
    assert result.dialog.id in group_creation_repo.groups
    saved_group = group_creation_repo.groups[result.dialog.id]
    assert saved_group.title.value == "Команда Проекта"
    assert saved_group.owner_id == alice_id
    assert saved_group.members == frozenset({alice_id, bob_id, charlie_id})

    # Check projections ensured: creator must be projected strictly first!
    assert group_projections.ensured_users[0] == alice_id
    assert set(group_projections.ensured_users) == {alice_id, bob_id, charlie_id}
    for member_id in (alice_id, bob_id, charlie_id):
        assert len(group_projections.for_user(member_id)) == 1


@pytest.mark.asyncio
async def test_create_group_requires_actor_registered(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    registered_users.users = frozenset({bob_id})  # alice is not registered
    attachments = make_attachments()

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=attachments,
        clock=clock.now,
        ids=ids.new_id,
    )

    with pytest.raises(UserNotRegisteredError) as exc_info:
        await handler(
            CreateGroupDialogCommand(
                actor_id=alice_id,
                title="Рабочая группа",
                initial_member_ids=(bob_id,),
            )
        )

    assert exc_info.value.user_id == alice_id
    assert len(group_creation_repo.groups) == 0


@pytest.mark.asyncio
async def test_create_group_requires_initial_members_registered(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    registered_users.users = frozenset({alice_id})  # bob is not registered
    attachments = make_attachments()

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=attachments,
        clock=clock.now,
        ids=ids.new_id,
    )

    with pytest.raises(UserNotRegisteredError) as exc_info:
        await handler(
            CreateGroupDialogCommand(
                actor_id=alice_id,
                title="Рабочая группа",
                initial_member_ids=(bob_id,),
            )
        )

    assert exc_info.value.user_id == bob_id
    assert len(group_creation_repo.groups) == 0


@pytest.mark.asyncio
async def test_create_group_requires_avatar_ready(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    avatar_id = UUID("01995140-0000-7000-8000-0000000000aa")

    registered_users.users = frozenset({alice_id, bob_id})
    attachments = make_attachments(ready_objects=set())  # avatar not ready

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        clock=clock.now,
        ids=ids.new_id,
        attachments=attachments,
    )

    with pytest.raises(StorageUnavailableError, match="not ready"):
        await handler(
            CreateGroupDialogCommand(
                actor_id=alice_id,
                title="Рабочая группа",
                initial_member_ids=(bob_id,),
                avatar_object_id=avatar_id,
            )
        )

    assert len(group_creation_repo.groups) == 0


@pytest.mark.asyncio
async def test_create_group_projection_failure_keeps_group_persisted(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    group_projections.failing_user_id = bob_id
    registered_users.users = frozenset({alice_id, bob_id})
    attachments = make_attachments()

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=attachments,
        clock=clock.now,
        ids=ids.new_id,
    )

    with pytest.raises(DialogProjectionsIncompleteError) as exc_info:
        await handler(
            CreateGroupDialogCommand(
                actor_id=alice_id,
                title="Рабочая группа",
                initial_member_ids=(bob_id,),
            )
        )

    assert exc_info.value.user_id == bob_id
    # Group was already persisted
    assert len(group_creation_repo.groups) == 1
    assert exc_info.value.dialog_id in group_creation_repo.groups


@pytest.mark.asyncio
async def test_create_group_empty_or_invalid_title(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
) -> None:
    registered_users.users = frozenset({alice_id})
    attachments = make_attachments()

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=attachments,
        clock=clock.now,
        ids=ids.new_id,
    )

    with pytest.raises(InvalidGroupTitleError):
        await handler(
            CreateGroupDialogCommand(
                actor_id=alice_id,
                title="   ",
            )
        )

    assert len(group_creation_repo.groups) == 0


@pytest.mark.asyncio
async def test_create_group_exceeding_capacity_fails_before_checking_registration(
    group_creation_repo,
    clock,
    ids,
    make_attachments,
    group_projections,
    registered_users,
    alice_id: UUID,
) -> None:
    too_many_members = tuple(
        UUID(f"01995140-0000-7000-8000-{i:012x}")
        for i in range(1, MAX_GROUP_MEMBERS + 1)
    )

    registered_users.users = frozenset()
    attachments = make_attachments()

    handler = CreateGroupDialogHandler(
        groups=group_creation_repo,
        projections=group_projections,
        registered_users=registered_users,
        attachments=attachments,
        clock=clock.now,
        ids=ids.new_id,
    )

    with pytest.raises(GroupMemberLimitExceededError):
        await handler(
            CreateGroupDialogCommand(
                actor_id=alice_id,
                title="Огромная группа",
                initial_member_ids=too_many_members,
            )
        )

    assert len(group_creation_repo.groups) == 0
