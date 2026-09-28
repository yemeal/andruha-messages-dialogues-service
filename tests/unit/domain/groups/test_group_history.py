from datetime import datetime, timedelta
from uuid import UUID

import pytest

from app.domain import (
    ClientMessageId,
    GroupDialog,
    MessageContent,
    MessageDeliveryPolicy,
    MessageDeliveryStatus,
    MessagePosition,
    MessagePostingPolicy,
    ReceiptWatermark,
)
from app.domain.exceptions import NotGroupMemberError


def test_new_member_can_read_history_even_after_its_author_leaves(
    alice_id: UUID, bob_id: UUID, outsider_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="History", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    arguments = dict(
        dialog=group,
        sender_id=bob_id,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("Before the new member joined"),
        position=MessagePosition(dialog_id=group.id, value=1),
    )
    message = MessagePostingPolicy.create_message(**arguments, now=now)
    group.add_member(outsider_id, now + timedelta(seconds=1), actor_id=alice_id)
    group.remove_member(bob_id, now + timedelta(seconds=2), actor_id=bob_id)
    group.require_can_read(outsider_id)
    watermark = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=outsider_id, now=now + timedelta(seconds=2)
    )

    assert watermark.advance_read(
        actor_id=outsider_id,
        dialog=group,
        through=message,
        now=now + timedelta(seconds=3),
    )
    assert (
        MessageDeliveryPolicy.calculate_status(
            message, watermark, dialog=group, recipient_id=outsider_id
        )
        is MessageDeliveryStatus.READ
    )

    with pytest.raises(NotGroupMemberError):
        group.require_can_read(bob_id)
    with pytest.raises(NotGroupMemberError):
        MessagePostingPolicy.create_message(**arguments, now=now + timedelta(seconds=4))
    with pytest.raises(NotGroupMemberError):
        MessageDeliveryPolicy.calculate_status(
            message, dialog=group, recipient_id=bob_id
        )
