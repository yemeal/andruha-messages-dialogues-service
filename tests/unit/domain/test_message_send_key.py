from datetime import datetime
from uuid import UUID, uuid7

from app.domain import (
    ClientMessageId,
    DirectDialog,
    DirectParticipants,
    MessageContent,
    MessagePosition,
    MessageSendKey,
)
from app.domain.policies.message_posting import MessagePostingPolicy


def test_send_key_is_scoped_to_sender_and_client_message_id(
    alice_id: UUID, bob_id: UUID
) -> None:
    client_message_id = ClientMessageId.generate()

    first = MessageSendKey(sender_id=alice_id, client_message_id=client_message_id)
    replay = MessageSendKey(sender_id=alice_id, client_message_id=client_message_id)
    another_sender = MessageSendKey(
        sender_id=bob_id, client_message_id=client_message_id
    )
    another_send = MessageSendKey(
        sender_id=alice_id, client_message_id=ClientMessageId.from_uuid(uuid7())
    )

    assert first == replay
    assert hash(first) == hash(replay)
    assert first != another_sender
    assert first != another_send


def test_message_exposes_stable_send_key(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(alice_id, bob_id), now=now
    )
    client_message_id = ClientMessageId.generate()
    message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=client_message_id,
        content=MessageContent.from_text("hello"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=now,
    )

    assert message.send_key == MessageSendKey(
        sender_id=alice_id, client_message_id=client_message_id
    )
