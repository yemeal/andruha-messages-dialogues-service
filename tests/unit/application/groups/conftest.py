import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.remove_member.handler import (
    RemoveGroupMemberHandler,
)
from app.application.commands.groups.send_message.handler import SendGroupMessageHandler
from app.application.ports.persistence.models import GroupSnapshot
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

    async def get_message(self, dialog_id: UUID, message_id: UUID) -> Message | None:
        message = self.messages.get(message_id)
        if message is None or message.dialog_id != dialog_id:
            return None
        return message.model_copy(deep=True)

    async def get_sent_message(
        self, dialog_id: UUID, send_key: MessageSendKey
    ) -> Message | None:
        for message in self.messages.values():
            if message.dialog_id == dialog_id and message.send_key == send_key:
                return message.model_copy(deep=True)
        return None

    async def get_receipt(
        self, dialog_id: UUID, user_id: UUID
    ) -> ReceiptWatermark | None:
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
        if self.pause_type is not None and isinstance(mutation, self.pause_type):
            self.pause_type = None
            self.entered.set()
            await self.resume.wait()
        async with self.lock:
            if expected.revision != self.current.revision:
                return False
            group = self.current.dialog
            last_position = self.current.last_position
            if isinstance(mutation, GroupDialog):
                group = mutation.model_copy(deep=True)
            elif isinstance(mutation, Message):
                self.messages[mutation.id] = mutation.model_copy(deep=True)
                last_position = mutation.position.value
            elif isinstance(mutation, ReceiptWatermark):
                self.receipts[mutation.user_id] = mutation.model_copy(deep=True)
            self.current = GroupSnapshot(
                dialog=group,
                revision=self.current.revision + 1,
                last_position=last_position,
            )
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
def remove_member(groups, clock, ids) -> RemoveGroupMemberHandler:
    return RemoveGroupMemberHandler(groups=groups, clock=clock.now, ids=ids.new_id)
