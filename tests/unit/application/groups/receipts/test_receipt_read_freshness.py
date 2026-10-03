from uuid import UUID

import pytest

from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
)
from app.application.commands.groups.advance_receipt.handler import (
    AdvanceGroupReceiptHandler,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.exceptions.groups import GroupReadConflictError
from app.application.ports.persistence.models import GroupMutation, GroupSnapshot
from app.domain.aggregates.receipt_watermark import ReceiptWatermark


class StaleReceiptReads:
    def __init__(self, repository, older: ReceiptWatermark) -> None:
        self.repository = repository
        self.older = older
        self.stale = True

    async def get_by_id(self, dialog_id: UUID):
        return await self.repository.get_by_id(dialog_id)

    async def get_message(
        self, dialog_id: UUID, message_id: UUID, *, at_revision: int | None = None
    ):
        return await self.repository.get_message(
            dialog_id, message_id, at_revision=at_revision
        )

    async def get_receipt(
        self, dialog_id: UUID, user_id: UUID, *, at_revision: int | None = None
    ):
        if self.stale:
            self.stale = False
            if at_revision is None:
                return self.older.model_copy(deep=True)
            raise GroupReadConflictError("Receipt replica has an older revision")
        return await self.repository.get_receipt(
            dialog_id, user_id, at_revision=at_revision
        )

    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        return await self.repository.try_commit(
            expected, mutation, command_id=command_id
        )


@pytest.mark.asyncio
async def test_old_receipt_read_cannot_roll_back_a_later_read_boundary(
    groups,
    send_message,
    advance_receipt,
    clock,
    ids,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    messages = []
    for value in range(3):
        accepted = await send_message(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=alice_id,
                client_message_id=UUID(int=value + 720, version=7),
                text=f"Message {value + 1}",
            )
        )
        messages.append(accepted.message)
    await advance_receipt(
        AdvanceGroupReceiptCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            kind="READ",
            through_message_id=messages[0].id,
        )
    )
    older = groups.receipts[bob_id].model_copy(deep=True)
    latest = await advance_receipt(
        AdvanceGroupReceiptCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            kind="READ",
            through_message_id=messages[2].id,
        )
    )
    before = groups.receipts[bob_id].model_dump()
    handler = AdvanceGroupReceiptHandler(
        StaleReceiptReads(groups, older), clock.now, ids.new_id
    )

    result = await handler(
        AdvanceGroupReceiptCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            kind="READ",
            through_message_id=messages[1].id,
        )
    )

    assert result.changed is False
    assert result.watermark == latest.watermark
    assert result.watermark.read_through.position == 3
    assert groups.receipts[bob_id].model_dump() == before
