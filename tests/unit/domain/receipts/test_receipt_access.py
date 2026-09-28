from datetime import datetime
from uuid import UUID

import pytest

from app.domain import (
    ClientMessageId,
    GroupDialog,
    MessageContent,
    MessagePosition,
    ReceiptWatermark,
)
from app.domain.exceptions import NotGroupMemberError
from app.domain.policies.message_delivery import MessageDeliveryPolicy
from app.domain.policies.message_posting import MessagePostingPolicy


def test_receipt_rejects_a_removed_group_member_without_mutation(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Team", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    message = MessagePostingPolicy.create_message(
        dialog=group,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("History"),
        position=MessagePosition(dialog_id=group.id, value=1),
        now=now,
    )
    watermark = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=bob_id, now=now
    )
    assert watermark.advance_read(
        actor_id=bob_id, dialog=group, through=message, now=now
    )
    group.remove_member(bob_id, now, actor_id=alice_id)
    before = watermark.model_dump()

    with pytest.raises(NotGroupMemberError):
        watermark.advance_read(actor_id=bob_id, dialog=group, through=message, now=now)

    assert watermark.model_dump() == before


def test_delivery_status_rejects_a_restored_outsider_watermark(
    alice_id: UUID, outsider_id: UUID, now: datetime
) -> None:
    from app.domain import MessageCheckpoint

    group = GroupDialog.create(title="Team", owner_id=alice_id, now=now)
    message = MessagePostingPolicy.create_message(
        dialog=group,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("Private history"),
        position=MessagePosition(dialog_id=group.id, value=1),
        now=now,
    )
    checkpoint = MessageCheckpoint.create(
        position=message.position, message_id=message.id, timestamp=now
    )
    watermark = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=outsider_id, now=now
    )
    restored = ReceiptWatermark.model_validate(
        {
            **watermark.model_dump(),
            "read_through": checkpoint.model_dump(),
            "delivered_through": checkpoint.model_dump(),
        }
    )

    with pytest.raises(NotGroupMemberError):
        MessageDeliveryPolicy.calculate_status(
            message, restored, dialog=group, recipient_id=outsider_id
        )
