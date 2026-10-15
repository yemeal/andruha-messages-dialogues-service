from uuid import UUID

import pytest

from app.application.commands.groups.change_avatar.command import (
    ChangeGroupAvatarCommand,
)
from app.application.commands.groups.change_avatar.handler import (
    ChangeGroupAvatarHandler,
)
from app.application.commands.groups.remove_avatar.command import (
    RemoveGroupAvatarCommand,
)
from app.application.commands.groups.remove_avatar.handler import (
    RemoveGroupAvatarHandler,
)
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import (
    GroupMetadataConflictError,
)
from app.application.ports.persistence.models import GroupSnapshot
from app.domain.exceptions.groups import NotGroupMemberError
from app.domain.value_objects.object_id import ObjectId


@pytest.fixture
def stranger_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000003")


@pytest.fixture
def avatar_id() -> UUID:
    return UUID("01995140-0000-7000-8000-0000000000aa")


@pytest.mark.asyncio
async def test_change_avatar_success(
    groups, bob_id: UUID, avatar_id: UUID, clock, make_attachments
) -> None:
    attachments = make_attachments({ObjectId.from_uuid(avatar_id)})
    handler = ChangeGroupAvatarHandler(
        groups=groups, attachments=attachments, clock=clock.now
    )

    command_id = UUID("01995140-0000-7000-8000-0000000000d1")
    # Bob is regular member, not owner, but can change avatar
    result = await handler(
        ChangeGroupAvatarCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=bob_id,
            command_id=command_id,
            avatar_object_id=avatar_id,
        )
    )

    assert result.avatar_object_id == avatar_id
    assert result.version == 2
    assert groups.current.dialog.avatar_object_id == ObjectId.from_uuid(avatar_id)


@pytest.mark.asyncio
async def test_change_avatar_unready_object_fails_before_commit(
    groups, alice_id: UUID, avatar_id: UUID, clock, make_attachments
) -> None:
    attachments = make_attachments(set())  # Empty
    handler = ChangeGroupAvatarHandler(
        groups=groups, attachments=attachments, clock=clock.now
    )

    with pytest.raises(StorageUnavailableError, match="not ready"):
        await handler(
            ChangeGroupAvatarCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=alice_id,
                command_id=UUID("01995140-0000-7000-8000-0000000000d2"),
                avatar_object_id=avatar_id,
            )
        )

    assert groups.current.revision == 1


@pytest.mark.asyncio
async def test_change_avatar_non_member_fails(
    groups, stranger_id: UUID, avatar_id: UUID, clock, make_attachments
) -> None:
    attachments = make_attachments({ObjectId.from_uuid(avatar_id)})
    handler = ChangeGroupAvatarHandler(
        groups=groups, attachments=attachments, clock=clock.now
    )

    with pytest.raises(NotGroupMemberError):
        await handler(
            ChangeGroupAvatarCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=stranger_id,
                command_id=UUID("01995140-0000-7000-8000-0000000000d3"),
                avatar_object_id=avatar_id,
            )
        )

    # Проверка прав участника произошла ДО внешнего RPC в Object Storage
    assert len(attachments.checked) == 0


@pytest.mark.asyncio
async def test_change_avatar_command_id_conflict(
    groups, alice_id: UUID, avatar_id: UUID, clock, make_attachments
) -> None:
    other_avatar_id = UUID("01995140-0000-7000-8000-0000000000bb")
    attachments = make_attachments(
        {ObjectId.from_uuid(avatar_id), ObjectId.from_uuid(other_avatar_id)}
    )
    handler = ChangeGroupAvatarHandler(
        groups=groups, attachments=attachments, clock=clock.now
    )

    command_id = UUID("01995140-0000-7000-8000-0000000000d9")
    await handler(
        ChangeGroupAvatarCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=alice_id,
            command_id=command_id,
            avatar_object_id=avatar_id,
        )
    )

    with pytest.raises(GroupMetadataConflictError):
        await handler(
            ChangeGroupAvatarCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=alice_id,
                command_id=command_id,
                avatar_object_id=other_avatar_id,
            )
        )


@pytest.mark.asyncio
async def test_change_avatar_verifies_attachment_only_once_on_cas_retries(
    groups, bob_id: UUID, avatar_id: UUID, clock, make_attachments
) -> None:
    attachments = make_attachments({ObjectId.from_uuid(avatar_id)})
    handler = ChangeGroupAvatarHandler(
        groups=groups, attachments=attachments, clock=clock.now, max_attempts=3
    )

    original_try_commit = groups.try_commit_metadata
    attempts = 0

    async def try_commit_with_conflict(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            groups.current = GroupSnapshot(
                dialog=groups.current.dialog,
                revision=groups.current.revision + 1,
                last_position=groups.current.last_position,
            )
            return False
        return await original_try_commit(*args, **kwargs)

    groups.try_commit_metadata = try_commit_with_conflict

    result = await handler(
        ChangeGroupAvatarCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=bob_id,
            command_id=UUID("01995140-0000-7000-8000-0000000000d7"),
            avatar_object_id=avatar_id,
        )
    )

    assert result.avatar_object_id == avatar_id
    assert attempts == 2
    # Attachment readiness must be verified only once despite CAS conflict retry
    assert len(attachments.checked) == 1


@pytest.mark.asyncio
async def test_remove_avatar_success(
    groups, alice_id: UUID, avatar_id: UUID, clock
) -> None:
    # First set avatar on group
    groups.current.dialog.change_avatar(avatar_id, now=clock.now(), actor_id=alice_id)
    handler = RemoveGroupAvatarHandler(groups=groups, clock=clock.now)

    result = await handler(
        RemoveGroupAvatarCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=alice_id,
            command_id=UUID("01995140-0000-7000-8000-0000000000d4"),
        )
    )

    assert result.avatar_object_id is None
    assert groups.current.dialog.avatar_object_id is None


@pytest.mark.asyncio
async def test_remove_avatar_no_avatar_is_noop(groups, alice_id: UUID, clock) -> None:
    handler = RemoveGroupAvatarHandler(groups=groups, clock=clock.now)

    result = await handler(
        RemoveGroupAvatarCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=alice_id,
            command_id=UUID("01995140-0000-7000-8000-0000000000d5"),
        )
    )

    assert result.avatar_object_id is None
    assert result.version == 1  # version not bumped for no-op
