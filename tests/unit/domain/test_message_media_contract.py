from datetime import datetime
from uuid import UUID, uuid7

from app.domain import (
    ClientMessageId,
    DirectDialog,
    DirectParticipants,
    Message,
    MessageContent,
    MessagePosition,
)
from app.domain.policies.message_posting import MessagePostingPolicy


def test_direct_message_can_contain_only_attachments(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(alice_id, bob_id), now=now
    )
    attachment = uuid7()
    message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_parts(attachments=(attachment,)),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=now,
    )

    assert message.text_value is None
    assert tuple(reference.value for reference in message.content.attachments) == (
        attachment,
    )
    assert message.model_dump(mode="json")["content"]["attachments"] == [
        str(attachment)
    ]
    assert Message.model_validate_json(message.model_dump_json()) == message
