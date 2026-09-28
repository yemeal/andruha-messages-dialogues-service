from datetime import datetime, timedelta
from uuid import UUID

import pytest

from app.domain import (
    ClientMessageId,
    DirectDialog,
    DirectParticipants,
    MessageContent,
    MessagePosition,
)
from app.domain.exceptions import NotDialogParticipantError


def test_posting_policy_checks_dialog_permissions_before_creating_a_message(
    alice_id: UUID, bob_id: UUID, outsider_id: UUID, now: datetime
) -> None:
    from app.domain.policies.message_posting import MessagePostingPolicy

    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(alice_id, bob_id), now=now
    )
    arguments = dict(
        dialog=dialog,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("Allowed"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=now + timedelta(seconds=1),
    )

    with pytest.raises(NotDialogParticipantError):
        MessagePostingPolicy.create_message(sender_id=outsider_id, **arguments)

    message = MessagePostingPolicy.create_message(sender_id=alice_id, **arguments)
    assert message.sender_id == alice_id
    assert message.dialog_id == dialog.id
    assert message.text_value == "Allowed"
