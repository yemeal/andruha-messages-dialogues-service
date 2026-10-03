import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.remove_member.handler import (
    RemoveGroupMemberHandler,
)
from app.application.commands.groups.send_message.handler import SendGroupMessageHandler
from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.groups import GroupReadConflictError
from app.application.ports.persistence.models import (
    GroupMembershipAcceptance,
    GroupMembershipIntent,
    GroupSnapshot,
)
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.message_send_key import MessageSendKey
from app.domain.value_objects.object_id import ObjectId


class ConditionalGroups:
    """Симуляция атомарного порта; не адаптер Cassandra."""

    def __init__(self, group: GroupDialog) -> None:
        self.current = GroupSnapshot(dialog=group, revision=1, last_position=0)
        self.messages: dict[UUID, Message] = {}
        self.receipts: dict[UUID, ReceiptWatermark] = {}
        self.membership_results: dict[tuple[UUID, UUID], GroupMembershipAcceptance] = {}
        self.lock = asyncio.Lock()
        self.pause_type: type | None = None
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()

    async def get_by_id(self, dialog_id: UUID) -> GroupSnapshot | None:
        if dialog_id != self.current.dialog.id:
            return None
        return GroupSnapshot(
            dialog=self.current.dialog.model_copy(deep=True),
            revision=self.current.revision,
            last_position=self.current.last_position,
        )

    def _require_revision(self, at_revision: int | None) -> None:
        if at_revision is not None and at_revision != self.current.revision:
            raise GroupReadConflictError("Group revision has changed")

    async def get_message(
        self, dialog_id: UUID, message_id: UUID, *, at_revision: int | None = None
    ) -> Message | None:
        self._require_revision(at_revision)
        message = self.messages.get(message_id)
        if message is None or message.dialog_id != dialog_id:
            return None
        return message.model_copy(deep=True)

    async def get_sent_message(
        self,
        dialog_id: UUID,
        send_key: MessageSendKey,
        *,
        at_revision: int | None = None,
    ) -> Message | None:
        self._require_revision(at_revision)
        for message in self.messages.values():
            if message.dialog_id == dialog_id and message.send_key == send_key:
                return message.model_copy(deep=True)
        return None

    async def get_receipt(
        self, dialog_id: UUID, user_id: UUID, *, at_revision: int | None = None
    ) -> ReceiptWatermark | None:
        self._require_revision(at_revision)
        receipt = self.receipts.get(user_id)
        if receipt is None or receipt.dialog_id != dialog_id:
            return None
        return receipt.model_copy(deep=True)

    async def try_commit(
        self,
        expected: GroupSnapshot,
        mutation: GroupDialog | Message | ReceiptWatermark | None,
        *,
        command_id: UUID,
    ) -> bool:
        return await self._try_commit(expected, mutation, command_id=command_id)

    async def get_membership_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ) -> GroupMembershipAcceptance | None:
        self._require_revision(at_revision)
        return self.membership_results.get((dialog_id, command_id))

    async def try_commit_membership(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupMembershipIntent,
    ) -> bool:
        acceptance = GroupMembershipAcceptance(
            intent=intent, result=GroupDialogDTO.from_domain(candidate)
        )
        return await self._try_commit(
            expected, candidate, command_id=command_id, acceptance=acceptance
        )

    async def _try_commit(
        self,
        expected: GroupSnapshot,
        mutation: GroupDialog | Message | ReceiptWatermark | None,
        *,
        command_id: UUID,
        acceptance: GroupMembershipAcceptance | None = None,
    ) -> bool:
        if self.pause_type is not None and isinstance(mutation, self.pause_type):
            self.pause_type = None
            self.entered.set()
            await self.resume.wait()
        async with self.lock:
            if expected.revision != self.current.revision:
                return False
            if acceptance is not None and (
                (expected.dialog.id, command_id) in self.membership_results
                or acceptance.intent.dialog_id != expected.dialog.id
            ):
                return False
            group = self.current.dialog
            last_position = self.current.last_position
            if isinstance(mutation, GroupDialog):
                group = mutation.model_copy(deep=True)
            elif isinstance(mutation, Message):
                if (
                    mutation.dialog_id != group.id
                    or mutation.id in self.messages
                    or any(
                        saved.send_key == mutation.send_key
                        for saved in self.messages.values()
                    )
                    or mutation.position.value != last_position + 1
                ):
                    return False
                self.messages[mutation.id] = mutation.model_copy(deep=True)
                last_position = mutation.position.value
            elif isinstance(mutation, ReceiptWatermark):
                if mutation.dialog_id != group.id:
                    return False
                saved = self.receipts.get(mutation.user_id)
                if saved is not None:
                    if mutation.id != saved.id or mutation.version != saved.version + 1:
                        return False
                    for candidate, previous in (
                        (mutation.read_through, saved.read_through),
                        (mutation.delivered_through, saved.delivered_through),
                    ):
                        if previous is not None and (
                            candidate is None
                            or candidate.position < previous.position
                            or (
                                candidate.position == previous.position
                                and candidate.message_id != previous.message_id
                            )
                        ):
                            return False
                self.receipts[mutation.user_id] = mutation.model_copy(deep=True)
            self.current = GroupSnapshot(
                dialog=group,
                revision=self.current.revision + 1,
                last_position=last_position,
            )
            if acceptance is not None:
                self.membership_results[(expected.dialog.id, command_id)] = acceptance
            return True


class ReadyAttachments:
    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        if attachments:
            raise ValueError("This fixture only confirms messages without attachments")


@pytest.fixture
def group_id() -> UUID:
    return UUID("01995140-0000-7000-8000-000000000900")


@pytest.fixture
def groups(group_id: UUID, alice_id: UUID, bob_id: UUID, clock) -> ConditionalGroups:
    return ConditionalGroups(
        GroupDialog.create(
            dialog_id=group_id,
            title="Рабочая группа",
            owner_id=alice_id,
            initial_members=(bob_id,),
            now=clock.now(),
        )
    )


@pytest.fixture
def send_message(groups, clock, ids) -> SendGroupMessageHandler:
    return SendGroupMessageHandler(
        groups=groups,
        clock=clock.now,
        ids=ids.new_id,
        attachments=ReadyAttachments(),
    )


@pytest.fixture
def remove_member(groups, clock) -> RemoveGroupMemberHandler:
    return RemoveGroupMemberHandler(groups=groups, clock=clock.now)
