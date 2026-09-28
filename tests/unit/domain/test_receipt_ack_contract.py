from datetime import datetime, timedelta
from uuid import UUID, uuid7

import pytest

from app.domain import (
    ClientMessageId,
    DirectDialog,
    DirectParticipants,
    GroupDialog,
    Message,
    MessageCheckpoint,
    MessageContent,
    MessagePosition,
    ReceiptWatermark,
)
from app.domain.exceptions.dialogues import NotDialogParticipantError
from app.domain.exceptions.receipts import (
    CheckpointMessageMismatchError,
    NotIncomingMessageError,
    ReceiptActorMismatchError,
    ReceiptDialogMismatchError,
)
from app.domain.policies.message_posting import MessagePostingPolicy


def _direct_case(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> tuple[DirectDialog, Message, ReceiptWatermark]:
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(alice_id, bob_id), now=now
    )
    message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=bob_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Hello"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=now,
    )
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog.id, user_id=alice_id, now=now
    )
    return dialog, message, watermark


def test_recipient_acknowledges_incoming_message(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog, message, watermark = _direct_case(alice_id, bob_id, now)

    changed = watermark.advance_delivered(
        actor_id=alice_id,
        dialog=dialog,
        through=message,
        now=now + timedelta(seconds=1),
    )

    assert changed is True
    assert watermark.delivered_through is not None
    assert watermark.delivered_through.dialog_id == dialog.id
    assert watermark.delivered_through.message_id == message.id
    assert watermark.delivered_through.position == message.position


def test_ack_rejects_other_actor_without_changing_watermark(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog, message, watermark = _direct_case(alice_id, bob_id, now)
    before = watermark.model_dump()

    with pytest.raises(ReceiptActorMismatchError):
        watermark.advance_read(actor_id=bob_id, dialog=dialog, through=message, now=now)

    assert watermark.model_dump() == before


def test_ack_rejects_outgoing_message_without_changing_watermark(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog, _, watermark = _direct_case(alice_id, bob_id, now)
    outgoing = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("My own message"),
        position=MessagePosition(dialog_id=dialog.id, value=2),
        now=now,
    )
    before = watermark.model_dump()

    with pytest.raises(NotIncomingMessageError):
        watermark.advance_delivered(
            actor_id=alice_id, dialog=dialog, through=outgoing, now=now
        )

    assert watermark.model_dump() == before


def test_ack_rejects_message_from_other_dialog_without_changing_watermark(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog, _, watermark = _direct_case(alice_id, bob_id, now)
    other_dialog = DirectDialog.create(participants=dialog.participants, now=now)
    foreign_message = MessagePostingPolicy.create_message(
        dialog=other_dialog,
        sender_id=bob_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Other dialog"),
        position=MessagePosition(dialog_id=other_dialog.id, value=1),
        now=now,
    )
    before = watermark.model_dump()

    with pytest.raises(ReceiptDialogMismatchError):
        watermark.advance_read(
            actor_id=alice_id, dialog=dialog, through=foreign_message, now=now
        )

    assert watermark.model_dump() == before


def test_ack_rejects_different_message_at_confirmed_position(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog, message, watermark = _direct_case(alice_id, bob_id, now)
    watermark.advance_delivered(
        actor_id=alice_id, dialog=dialog, through=message, now=now
    )
    conflicting_message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=bob_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Conflicting message"),
        position=message.position,
        now=now,
    )
    before = watermark.model_dump()

    with pytest.raises(CheckpointMessageMismatchError):
        watermark.advance_delivered(
            actor_id=alice_id,
            dialog=dialog,
            through=conflicting_message,
            now=now + timedelta(seconds=1),
        )

    assert watermark.model_dump() == before


def test_group_ack_rejects_nonmember_and_sender(now: datetime) -> None:
    owner_id = uuid7()
    member_id = uuid7()
    outsider_id = uuid7()
    group = GroupDialog.create(
        title="Team", owner_id=owner_id, initial_members=[member_id], now=now
    )
    message = MessagePostingPolicy.create_message(
        dialog=group,
        sender_id=owner_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Update"),
        position=MessagePosition(dialog_id=group.id, value=1),
        now=now,
    )
    outsider_watermark = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=outsider_id, now=now
    )
    sender_watermark = ReceiptWatermark.create_empty(
        dialog_id=group.id, user_id=owner_id, now=now
    )

    with pytest.raises(NotDialogParticipantError):
        outsider_watermark.advance_delivered(
            actor_id=outsider_id, dialog=group, through=message, now=now
        )
    with pytest.raises(NotIncomingMessageError):
        sender_watermark.advance_read(
            actor_id=owner_id, dialog=group, through=message, now=now
        )

    assert outsider_watermark.delivered_through is None
    assert sender_watermark.read_through is None


def test_empty_watermark_rejects_position_from_another_dialog(
    dialog_id: UUID, alice_id: UUID, now: datetime
) -> None:
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog_id, user_id=alice_id, now=now
    )
    foreign_position = MessagePosition(dialog_id=uuid7(), value=1)

    with pytest.raises(ReceiptDialogMismatchError):
        watermark.is_delivered(foreign_position)


def test_restored_watermark_rejects_foreign_checkpoint(
    dialog_id: UUID, alice_id: UUID, now: datetime
) -> None:
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog_id, user_id=alice_id, now=now
    )
    foreign_checkpoint = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=uuid7(), value=1),
        message_id=uuid7(),
        timestamp=now,
    )

    with pytest.raises(ReceiptDialogMismatchError):
        ReceiptWatermark.model_validate(
            {
                **watermark.model_dump(),
                "delivered_through": foreign_checkpoint.model_dump(),
            }
        )
