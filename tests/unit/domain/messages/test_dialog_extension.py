from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from app.domain import (
    ClientMessageId,
    Message,
    MessageContent,
    MessageDeliveryPolicy,
    MessageDeliveryStatus,
    MessagePosition,
    MessagePostingPolicy,
    ReceiptWatermark,
)
from app.domain.exceptions import NotDialogParticipantError


@dataclass(frozen=True)
class AnnouncementDialog:
    """Четвёртый тип: публикует владелец, читают подписчики."""

    id: UUID
    created_at: datetime
    publisher_id: UUID
    subscribers: frozenset[UUID]

    @property
    def supports_receipts(self) -> bool:
        return True

    def require_can_send(self, user_id: UUID) -> None:
        if user_id != self.publisher_id:
            raise NotDialogParticipantError()

    def require_message_access(self, *, sender_id: UUID, reader_id: UUID) -> None:
        if sender_id != self.publisher_id or reader_id not in self.subscribers:
            raise NotDialogParticipantError()


def test_new_dialog_type_supports_posting_receipts_and_delivery_without_message_changes(
    alice_id: UUID,
    bob_id: UUID,
    outsider_id: UUID,
    dialog_id: UUID,
    now: datetime,
) -> None:
    dialog = AnnouncementDialog(dialog_id, now, alice_id, frozenset({bob_id}))
    send_arguments = dict(
        dialog=dialog,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("Announcement"),
        position=MessagePosition(dialog_id=dialog_id, value=1),
        message_id=UUID("01995140-0000-7000-8000-000000000010"),
        now=now,
    )

    with pytest.raises(NotDialogParticipantError):
        MessagePostingPolicy.create_message(sender_id=bob_id, **send_arguments)

    created = MessagePostingPolicy.create_message(sender_id=alice_id, **send_arguments)
    message = Message.model_validate_json(created.model_dump_json())
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog_id, user_id=bob_id, now=now
    )
    assert message == created
    assert (
        MessageDeliveryPolicy.status_for(
            message, watermark, dialog=dialog, recipient_id=bob_id
        )
        is MessageDeliveryStatus.SENT
    )
    assert watermark.advance_read(
        actor_id=bob_id, dialog=dialog, through=message, now=now + timedelta(seconds=1)
    )
    assert (
        MessageDeliveryPolicy.status_for(
            message, watermark, dialog=dialog, recipient_id=bob_id
        )
        is MessageDeliveryStatus.READ
    )

    with pytest.raises(NotDialogParticipantError):
        MessageDeliveryPolicy.status_for(
            message, dialog=dialog, recipient_id=outsider_id
        )
