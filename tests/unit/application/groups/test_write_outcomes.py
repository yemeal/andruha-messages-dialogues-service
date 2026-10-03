from uuid import UUID

import pytest

from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.remove_member.handler import (
    RemoveGroupMemberHandler,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.commands.groups.send_message.handler import SendGroupMessageHandler
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import ConcurrentModificationError
from app.application.ports.persistence.models import (
    GroupMembershipIntent,
    GroupMutation,
    GroupSnapshot,
)
from app.domain.aggregates.group_dialog import GroupDialog


class WriteOutcomeGroups:
    def __init__(self, repository, *, commit_then_fail: bool) -> None:
        self.repository = repository
        self.commit_then_fail = commit_then_fail
        self.attempts = 0

    async def get_by_id(self, dialog_id: UUID):
        return await self.repository.get_by_id(dialog_id)

    async def get_message(self, dialog_id: UUID, message_id: UUID, *, at_revision: int):
        return await self.repository.get_message(
            dialog_id, message_id, at_revision=at_revision
        )

    async def get_sent_message(self, dialog_id: UUID, send_key, *, at_revision: int):
        return await self.repository.get_sent_message(
            dialog_id, send_key, at_revision=at_revision
        )

    async def get_receipt(self, dialog_id: UUID, user_id: UUID, *, at_revision: int):
        return await self.repository.get_receipt(
            dialog_id, user_id, at_revision=at_revision
        )

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
        self.attempts += 1
        if self.commit_then_fail:
            await self.repository.try_commit_membership(
                expected, candidate, command_id=command_id, intent=intent
            )
            raise StorageUnavailableError("Commit outcome is not confirmed")
        return False

    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        self.attempts += 1
        if self.commit_then_fail:
            await self.repository.try_commit(expected, mutation, command_id=command_id)
            raise StorageUnavailableError("Commit outcome is not confirmed")
        return False


class NoAttachments:
    async def require_ready(self, sender_id: UUID, attachments: tuple) -> None:
        raise AssertionError("This scenario has no attachments")


@pytest.mark.asyncio
async def test_unknown_write_outcome_does_not_report_success_or_retry_as_conflict(
    groups, send_message, clock, ids, group_id: UUID, bob_id: UUID
) -> None:
    uncertain = WriteOutcomeGroups(groups, commit_then_fail=True)
    handler = SendGroupMessageHandler(uncertain, clock.now, ids.new_id, NoAttachments())
    command = SendGroupMessageCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        client_message_id=UUID("01995140-0000-7000-8000-000000000501"),
        text="Исход записи потерян",
    )
    with pytest.raises(StorageUnavailableError):
        await handler(command)

    assert uncertain.attempts == 1
    assert len(groups.messages) == 1
    recovered = await send_message(command)
    assert recovered.message.position == 1
    assert recovered.message.client_message_id == command.client_message_id
    assert len(groups.messages) == 1


@pytest.mark.asyncio
async def test_confirmed_conflicts_are_bounded_without_modifying_group(
    groups, clock, ids, group_id: UUID, alice_id: UUID, bob_id: UUID
) -> None:
    conflicts = WriteOutcomeGroups(groups, commit_then_fail=False)
    handler = RemoveGroupMemberHandler(conflicts, clock.now, max_attempts=2)
    before = groups.current.dialog.model_dump()

    with pytest.raises(ConcurrentModificationError):
        await handler(
            RemoveGroupMemberCommand(
                command_id=UUID("01995140-0000-7000-8000-000000000790"),
                dialog_id=group_id,
                actor_id=alice_id,
                user_id=bob_id,
            )
        )

    assert conflicts.attempts == 2
    assert groups.current.dialog.model_dump() == before
    assert groups.current.revision == 1
