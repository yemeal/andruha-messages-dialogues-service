import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
)
from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.exceptions.groups import NotGroupMemberError


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["DELIVERED", "READ"])
async def test_removed_member_cannot_commit_ack_from_stale_group_snapshot(
    groups,
    send_message,
    advance_receipt,
    remove_member,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
    kind: str,
) -> None:
    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=alice_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000201"),
            text="Входящее сообщение",
        )
    )
    groups.pause_type = ReceiptWatermark
    pending = asyncio.create_task(
        advance_receipt(
            AdvanceGroupReceiptCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                kind=kind,
                through_message_id=sent.message.id,
            )
        )
    )
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        await remove_member(
            RemoveGroupMemberCommand(
                dialog_id=group_id, actor_id=alice_id, user_id=bob_id
            )
        )
        groups.resume.set()
        with pytest.raises(NotGroupMemberError):
            await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    assert await groups.get_receipt(group_id, bob_id) is None
    assert sent.message.id in groups.messages
