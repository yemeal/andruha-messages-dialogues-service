import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.add_member.command import AddGroupMemberCommand
from app.application.commands.groups.add_member.handler import AddGroupMemberHandler
from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.remove_member.handler import (
    RemoveGroupMemberHandler,
)
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import GroupMembershipConflictError
from app.application.ports.persistence.models import (
    GroupMembershipIntent,
    GroupSnapshot,
    MembershipAction,
)
from app.domain.aggregates.group_dialog import GroupDialog


class LostMembershipReply:
    """Запись прошла, но первый ответ хранилища потерян."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self.fail_once = True

    async def get_by_id(self, dialog_id: UUID):
        return await self.repository.get_by_id(dialog_id)

    async def get_membership_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ):
        return await self.repository.get_membership_result(
            dialog_id, command_id, at_revision=at_revision
        )

    async def try_commit_membership(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupMembershipIntent,
    ) -> bool:
        committed = await self.repository.try_commit_membership(
            expected, candidate, command_id=command_id, intent=intent
        )
        if committed and self.fail_once:
            self.fail_once = False
            raise StorageUnavailableError("Membership write reply was lost")
        return committed


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [MembershipAction.ADD, MembershipAction.REMOVE])
async def test_retry_after_unknown_membership_write_restores_the_saved_result(
    groups,
    registered_users,
    clock,
    ids,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
    action: MembershipAction,
) -> None:
    user_id = UUID(int=1006, version=4) if action is MembershipAction.ADD else bob_id
    registered_users.users |= {user_id}
    command_id = UUID("01995140-0000-7000-8000-000000000750")
    repository = LostMembershipReply(groups)
    command_type = (
        AddGroupMemberCommand
        if action is MembershipAction.ADD
        else RemoveGroupMemberCommand
    )
    command = command_type(
        command_id=command_id, dialog_id=group_id, actor_id=alice_id, user_id=user_id
    )
    handler = (
        AddGroupMemberHandler(repository, registered_users, clock.now)
        if action is MembershipAction.ADD
        else RemoveGroupMemberHandler(repository, clock.now)
    )
    with pytest.raises(StorageUnavailableError):
        await handler(command)
    before = groups.current.dialog.model_dump()
    revision = groups.current.revision

    recovered = await handler(command)

    assert recovered.id == group_id
    assert recovered.version == 2
    assert (user_id in recovered.members) is (action is MembershipAction.ADD)
    assert groups.current.dialog.model_dump() == before
    assert groups.current.revision == revision
    assert len(groups.membership_results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [MembershipAction.ADD, MembershipAction.REMOVE])
async def test_old_membership_replay_does_not_undo_a_later_opposite_command(
    groups,
    registered_users,
    clock,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
    action: MembershipAction,
) -> None:
    user_id = UUID(int=1007, version=4) if action is MembershipAction.ADD else bob_id
    registered_users.users |= {user_id}
    add = AddGroupMemberHandler(groups, registered_users, clock.now)
    remove = RemoveGroupMemberHandler(groups, clock.now)
    command_type = (
        AddGroupMemberCommand
        if action is MembershipAction.ADD
        else RemoveGroupMemberCommand
    )
    opposite_type = (
        RemoveGroupMemberCommand
        if action is MembershipAction.ADD
        else AddGroupMemberCommand
    )
    handler = add if action is MembershipAction.ADD else remove
    opposite_handler = remove if action is MembershipAction.ADD else add
    original = command_type(
        command_id=UUID("01995140-0000-7000-8000-000000000751"),
        dialog_id=group_id,
        actor_id=alice_id,
        user_id=user_id,
    )
    first = await handler(original)
    await opposite_handler(
        opposite_type(
            command_id=UUID("01995140-0000-7000-8000-000000000752"),
            dialog_id=group_id,
            actor_id=alice_id,
            user_id=user_id,
        )
    )
    before = groups.current.dialog.model_dump()
    revision = groups.current.revision
    registered_users.users -= {user_id}

    replay = await handler(original)

    assert replay == first
    assert replay.version == 2
    assert groups.current.dialog.version == 3
    assert groups.current.dialog.model_dump() == before
    assert groups.current.revision == revision
    assert (user_id in groups.current.dialog) is (action is MembershipAction.REMOVE)
    assert len(groups.membership_results) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["action", "actor", "user"])
async def test_membership_command_id_cannot_be_reused_for_another_intent(
    groups,
    registered_users,
    clock,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
    change: str,
) -> None:
    user_id = UUID(int=1008, version=4)
    other_id = UUID(int=1009, version=4)
    registered_users.users |= {user_id, other_id}
    command_id = UUID("01995140-0000-7000-8000-000000000753")
    add = AddGroupMemberHandler(groups, registered_users, clock.now)
    await add(
        AddGroupMemberCommand(
            command_id=command_id,
            dialog_id=group_id,
            actor_id=alice_id,
            user_id=user_id,
        )
    )
    before = groups.current.dialog.model_dump()
    revision = groups.current.revision
    command_type = (
        RemoveGroupMemberCommand if change == "action" else AddGroupMemberCommand
    )
    handler = RemoveGroupMemberHandler(groups, clock.now) if change == "action" else add
    command = command_type(
        command_id=command_id,
        dialog_id=group_id,
        actor_id=bob_id if change == "actor" else alice_id,
        user_id=other_id if change == "user" else user_id,
    )

    with pytest.raises(GroupMembershipConflictError):
        await handler(command)

    assert groups.current.dialog.model_dump() == before
    assert groups.current.revision == revision
    assert len(groups.membership_results) == 1


@pytest.mark.asyncio
async def test_concurrent_retries_of_one_membership_command_apply_it_once(
    groups,
    registered_users,
    clock,
    group_id: UUID,
    alice_id: UUID,
) -> None:
    user_id = UUID(int=1010, version=4)
    registered_users.users |= {user_id}
    handler = AddGroupMemberHandler(groups, registered_users, clock.now)
    command = AddGroupMemberCommand(
        command_id=UUID("01995140-0000-7000-8000-000000000754"),
        dialog_id=group_id,
        actor_id=alice_id,
        user_id=user_id,
    )
    groups.pause_type = GroupDialog
    pending = asyncio.create_task(handler(command))
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        winner = await handler(command)
        groups.resume.set()
        replay = await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    assert replay == winner
    assert winner.version == 2
    assert user_id in groups.current.dialog
    assert groups.current.revision == 2
    assert len(groups.membership_results) == 1
