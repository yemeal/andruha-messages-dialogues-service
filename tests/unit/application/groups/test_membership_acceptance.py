from uuid import UUID

import pytest

from app.application.commands.groups.add_member.command import AddGroupMemberCommand
from app.application.commands.groups.add_member.handler import AddGroupMemberHandler
from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.exceptions.dialogues import UserNotRegisteredError
from app.application.exceptions.groups import DialogNotFoundError
from app.domain.exceptions.groups import CannotRemoveOwnerError


@pytest.mark.asyncio
async def test_registration_failure_does_not_apply_candidate_membership(
    registered_users, groups, clock, ids, group_id: UUID, alice_id: UUID
) -> None:
    handler = AddGroupMemberHandler(groups, registered_users, clock.now, ids.new_id)
    candidate = UUID(int=1005, version=4)
    before = groups.current.dialog.model_dump()

    with pytest.raises(UserNotRegisteredError):
        await handler(
            AddGroupMemberCommand(
                dialog_id=group_id, actor_id=alice_id, user_id=candidate
            )
        )

    assert groups.current.dialog.model_dump() == before
    assert candidate not in groups.current.dialog
    assert groups.current.revision == 1


@pytest.mark.asyncio
async def test_owner_removal_is_rejected_without_changing_group(
    remove_member, groups, group_id: UUID, alice_id: UUID, bob_id: UUID
) -> None:
    before = groups.current.dialog.model_dump()
    with pytest.raises(CannotRemoveOwnerError):
        await remove_member(
            RemoveGroupMemberCommand(
                dialog_id=group_id, actor_id=bob_id, user_id=alice_id
            )
        )

    assert groups.current.dialog.model_dump() == before
    assert groups.current.revision == 1


@pytest.mark.asyncio
async def test_missing_group_is_an_application_error_without_writing(
    remove_member, groups, alice_id: UUID, bob_id: UUID
) -> None:
    missing_id = UUID("01995140-0000-7000-8000-000000000999")
    with pytest.raises(DialogNotFoundError) as error:
        await remove_member(
            RemoveGroupMemberCommand(
                dialog_id=missing_id, actor_id=alice_id, user_id=bob_id
            )
        )

    assert error.value.dialog_id == missing_id
    assert groups.current.revision == 1
