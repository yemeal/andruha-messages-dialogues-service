from uuid import uuid7

import pytest

from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.clock import utc_now
from app.domain.exceptions.messages import (
    WatermarkDialogMismatchError,
    WatermarkRecipientMismatchError,
)
from app.domain.exceptions.receipts import (
    CheckpointMessageMismatchError,
    NotIncomingMessageError,
)
from app.domain.policies.message_delivery import (
    MessageDeliveryPolicy,
    MessageDeliveryStatus,
)
from app.domain.policies.message_posting import MessagePostingPolicy
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_checkpoint import MessageCheckpoint
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition


def _setup_dialog_and_message(
    pos_val: int = 10,
) -> tuple[DirectDialog, Message, ReceiptWatermark]:
    t0 = utc_now()
    sender_id = uuid7()
    recipient_id = uuid7()
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(sender_id, recipient_id),
        now=t0,
    )
    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=sender_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Test policy message"),
        position=MessagePosition(dialog_id=dialog.id, value=pos_val),
        now=t0,
    )
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog.id,
        user_id=recipient_id,
        now=t0,
    )
    return dialog, msg, watermark


def test_status_when_no_watermark_is_sent() -> None:
    dialog, msg, watermark = _setup_dialog_and_message()
    status = MessageDeliveryPolicy.calculate_status(
        msg, None, dialog=dialog, recipient_id=watermark.user_id
    )
    assert status == MessageDeliveryStatus.SENT

    alias_status = MessageDeliveryPolicy.status_for(
        msg, None, dialog=dialog, recipient_id=watermark.user_id
    )
    assert alias_status == MessageDeliveryStatus.SENT


def test_status_when_watermark_empty_is_sent() -> None:
    dialog, msg, watermark = _setup_dialog_and_message(pos_val=10)
    assert watermark.delivered_through is None
    assert watermark.read_through is None

    status = MessageDeliveryPolicy.calculate_status(
        msg, watermark, dialog=dialog, recipient_id=watermark.user_id
    )
    assert status == MessageDeliveryStatus.SENT


def test_status_delivered_when_position_is_delivered_but_not_read() -> None:
    dialog, msg, watermark = _setup_dialog_and_message(pos_val=10)
    t = utc_now()
    watermark.advance_delivered(
        actor_id=watermark.user_id, dialog=dialog, through=msg, now=t
    )

    status = MessageDeliveryPolicy.calculate_status(
        msg, watermark, dialog=dialog, recipient_id=watermark.user_id
    )
    assert status == MessageDeliveryStatus.DELIVERED


def test_status_read_when_position_is_read() -> None:
    dialog, msg, watermark = _setup_dialog_and_message(pos_val=10)
    t = utc_now()
    watermark.advance_read(
        actor_id=watermark.user_id, dialog=dialog, through=msg, now=t
    )

    status = MessageDeliveryPolicy.calculate_status(
        msg, watermark, dialog=dialog, recipient_id=watermark.user_id
    )
    assert status == MessageDeliveryStatus.READ


def test_status_when_position_exceeds_watermark_is_sent() -> None:
    dialog, msg, watermark = _setup_dialog_and_message(pos_val=20)
    t = utc_now()
    earlier_message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=msg.sender_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Earlier message"),
        position=MessagePosition(dialog_id=dialog.id, value=10),
        now=t,
    )
    watermark.advance_read(
        actor_id=watermark.user_id, dialog=dialog, through=earlier_message, now=t
    )

    # watermark is at 10, message is at 20 -> still SENT
    status = MessageDeliveryPolicy.calculate_status(
        msg, watermark, dialog=dialog, recipient_id=watermark.user_id
    )
    assert status == MessageDeliveryStatus.SENT


def test_status_rejects_different_message_at_confirmed_position() -> None:
    dialog, message, watermark = _setup_dialog_and_message()
    watermark.advance_delivered(
        actor_id=watermark.user_id,
        dialog=dialog,
        through=message,
        now=utc_now(),
    )
    conflicting_message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=message.sender_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Collision"),
        position=message.position,
        now=utc_now(),
    )

    with pytest.raises(CheckpointMessageMismatchError):
        MessageDeliveryPolicy.calculate_status(
            conflicting_message,
            watermark,
            dialog=dialog,
            recipient_id=watermark.user_id,
        )


def test_rejects_watermark_for_wrong_dialog() -> None:
    dialog, msg, watermark = _setup_dialog_and_message()
    other_dialog_watermark = ReceiptWatermark.create_empty(
        dialog_id=uuid7(),
        user_id=watermark.user_id,
    )

    with pytest.raises(WatermarkDialogMismatchError):
        MessageDeliveryPolicy.calculate_status(
            msg, other_dialog_watermark, dialog=dialog, recipient_id=watermark.user_id
        )


def test_rejects_watermark_for_wrong_user() -> None:
    dialog, msg, watermark = _setup_dialog_and_message()
    other_user_watermark = ReceiptWatermark.create_empty(
        dialog_id=msg.dialog_id,
        user_id=msg.sender_id,  # Sender's watermark instead of recipient's
    )

    with pytest.raises(WatermarkRecipientMismatchError):
        MessageDeliveryPolicy.calculate_status(
            msg, other_user_watermark, dialog=dialog, recipient_id=watermark.user_id
        )


def test_group_message_delivery_status_for_members() -> None:
    from app.domain.aggregates.group_dialog import GroupDialog

    owner = uuid7()
    member1 = uuid7()
    member2 = uuid7()
    t0 = utc_now()
    group = GroupDialog.create(
        title="Squad",
        owner_id=owner,
        initial_members=[member1, member2],
        now=t0,
    )

    msg = MessagePostingPolicy.create_message(
        dialog=group,
        sender_id=owner,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Deploy ready"),
        position=MessagePosition(dialog_id=group.id, value=10),
        now=t0,
    )

    # Member 1 read the message
    watermark_m1 = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=member1, now=t0
    )
    watermark_m1.advance_read(actor_id=member1, dialog=group, through=msg, now=t0)
    assert (
        MessageDeliveryPolicy.calculate_status(
            msg, watermark_m1, dialog=group, recipient_id=member1
        )
        == MessageDeliveryStatus.READ
    )

    # Member 2 delivered the message
    watermark_m2 = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=member2, now=t0
    )
    watermark_m2.advance_delivered(actor_id=member2, dialog=group, through=msg, now=t0)
    assert (
        MessageDeliveryPolicy.calculate_status(
            msg, watermark_m2, dialog=group, recipient_id=member2
        )
        == MessageDeliveryStatus.DELIVERED
    )

    # Sender cannot acknowledge receipt of own group message
    watermark_owner = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=owner, now=t0
    )
    with pytest.raises(WatermarkRecipientMismatchError):
        MessageDeliveryPolicy.calculate_status(
            msg, watermark_owner, dialog=group, recipient_id=owner
        )


def test_saved_message_delivery_status() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    outsider = uuid7()
    t0 = utc_now()
    saved = SavedDialog.create(user_id=user_id, now=t0)

    msg = MessagePostingPolicy.create_message(
        dialog=saved,
        sender_id=user_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("My note"),
        position=MessagePosition(dialog_id=saved.id, value=10),
        now=t0,
    )

    # Empty watermark -> SENT
    watermark = ReceiptWatermark.create_empty(
        dialog_id=saved.id, user_id=user_id, now=t0
    )
    assert (
        MessageDeliveryPolicy.calculate_status(
            msg, watermark, dialog=saved, recipient_id=user_id
        )
        == MessageDeliveryStatus.SENT
    )

    # Saved messages have no incoming recipient, so they cannot receive ACKs.
    with pytest.raises(NotIncomingMessageError):
        watermark.advance_delivered(actor_id=user_id, dialog=saved, through=msg, now=t0)
    with pytest.raises(NotIncomingMessageError):
        watermark.advance_read(actor_id=user_id, dialog=saved, through=msg, now=t0)
    assert (
        MessageDeliveryPolicy.calculate_status(
            msg, watermark, dialog=saved, recipient_id=user_id
        )
        == MessageDeliveryStatus.SENT
    )

    # Outsider watermark on saved dialog rejected
    outsider_watermark = ReceiptWatermark.create_empty(
        dialog_id=saved.id, user_id=outsider, now=t0
    )
    with pytest.raises(WatermarkRecipientMismatchError):
        MessageDeliveryPolicy.calculate_status(
            msg, outsider_watermark, dialog=saved, recipient_id=user_id
        )


def test_saved_message_has_no_delivery_receipt_even_from_restored_watermark() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    now = utc_now()
    saved = SavedDialog.create(user_id=user_id, now=now)
    message = MessagePostingPolicy.create_message(
        dialog=saved,
        sender_id=user_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("My note"),
        position=MessagePosition(dialog_id=saved.id, value=1),
        now=now,
    )
    watermark = ReceiptWatermark.create_empty(
        dialog_id=saved.id, user_id=user_id, now=now
    )
    checkpoint = MessageCheckpoint.create(
        position=message.position, message_id=message.id, timestamp=message.created_at
    )
    restored = ReceiptWatermark.model_validate(
        {**watermark.model_dump(), "delivered_through": checkpoint.model_dump()}
    )

    assert (
        MessageDeliveryPolicy.calculate_status(
            message, restored, dialog=saved, recipient_id=user_id
        )
        == MessageDeliveryStatus.SENT
    )
