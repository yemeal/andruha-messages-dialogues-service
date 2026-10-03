from uuid import UUID

import pytest

from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
)
from app.application.commands.groups.advance_receipt.handler import (
    AdvanceGroupReceiptHandler,
)
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.ports.persistence.models import GroupMutation, GroupSnapshot
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition


class SharedReceiptRepository:
    """Диагностический порт возвращает общий объект и отказывает в записи."""

    def __init__(self, repository) -> None:
        self.repository = repository

    async def get_by_id(self, dialog_id: UUID):
        return await self.repository.get_by_id(dialog_id)

    async def get_message(self, dialog_id: UUID, message_id: UUID, *, at_revision: int):
        return await self.repository.get_message(
            dialog_id, message_id, at_revision=at_revision
        )

    async def get_receipt(self, dialog_id: UUID, user_id: UUID, *, at_revision: int):
        await self.repository.get_receipt(dialog_id, user_id, at_revision=at_revision)
        return self.repository.receipts.get(user_id)

    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        raise StorageUnavailableError("Write was rejected")


@pytest.mark.asyncio
async def test_failed_ack_does_not_mutate_a_receipt_shared_by_the_repository(
    groups, clock, ids, group_id: UUID, alice_id: UUID, bob_id: UUID
) -> None:
    through = Message.create(
        message_id=ids.new_id(),
        dialog_id=group_id,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_uuid(ids.new_id()),
        content=MessageContent.from_text("Входящее сообщение"),
        position=MessagePosition(dialog_id=group_id, value=1),
        now=clock.now(),
    )
    groups.messages[through.id] = through
    stored = ReceiptWatermark.create_empty(
        dialog_id=group_id,
        user_id=bob_id,
        watermark_id=ids.new_id(),
        now=clock.now(),
    )
    groups.receipts[bob_id] = stored
    before = stored.model_dump()
    revision = groups.current.revision
    handler = AdvanceGroupReceiptHandler(
        SharedReceiptRepository(groups), clock.now, ids.new_id
    )

    with pytest.raises(StorageUnavailableError):
        await handler(
            AdvanceGroupReceiptCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                kind="READ",
                through_message_id=through.id,
            )
        )

    assert stored.model_dump() == before
    assert groups.receipts[bob_id].model_dump() == before
    assert groups.current.revision == revision
