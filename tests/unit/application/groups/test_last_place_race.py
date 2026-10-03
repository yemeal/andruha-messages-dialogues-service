import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.add_member.command import AddGroupMemberCommand
from app.application.commands.groups.add_member.handler import AddGroupMemberHandler
from app.application.ports.persistence.models import GroupSnapshot
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.exceptions.groups import GroupMemberLimitExceededError


@pytest.mark.asyncio
async def test_two_candidates_for_last_group_place_accept_exactly_one(
    groups,
    registered_users,
    clock,
    ids,
    group_id: UUID,
    alice_id: UUID,
) -> None:
    first_id = UUID(int=1001, version=4)
    second_id = UUID(int=1002, version=4)
    registered_users.users |= {first_id, second_id}
    group = GroupDialog.create(
        dialog_id=group_id,
        title="Почти полная группа",
        owner_id=alice_id,
        initial_members=tuple(UUID(int=value, version=4) for value in range(2, 1000)),
        now=clock.now(),
    )
    assert group.member_count == 999
    groups.current = GroupSnapshot(dialog=group, revision=1, last_position=0)
    first_handler = AddGroupMemberHandler(groups, registered_users, clock.now)
    second_handler = AddGroupMemberHandler(
        groups,
        registered_users,
        clock.now,
    )
    groups.pause_type = GroupDialog
    pending = asyncio.create_task(
        first_handler(
            AddGroupMemberCommand(
                command_id=UUID("01995140-0000-7000-8000-000000000788"),
                dialog_id=group_id,
                actor_id=alice_id,
                user_id=first_id,
            )
        )
    )
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        winner = await second_handler(
            AddGroupMemberCommand(
                command_id=UUID("01995140-0000-7000-8000-000000000789"),
                dialog_id=group_id,
                actor_id=alice_id,
                user_id=second_id,
            )
        )
        groups.resume.set()
        with pytest.raises(GroupMemberLimitExceededError):
            await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    assert len(winner.members) == 1000
    assert groups.current.dialog.member_count == 1000
    assert first_id not in groups.current.dialog
    assert second_id in groups.current.dialog
    assert groups.current.dialog.version == 2
    assert groups.current.revision == 2
