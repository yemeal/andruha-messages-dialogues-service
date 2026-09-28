from copy import deepcopy
from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain import ClientMessageId, Message, MessageContent, MessagePosition


def test_message_is_created_and_restored_without_dialog_type_or_recipient(
    alice_id: UUID, dialog_id: UUID, now: datetime
) -> None:
    message = Message.create(
        dialog_id=dialog_id,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("Independent message"),
        position=MessagePosition(dialog_id=dialog_id, value=1),
        message_id=UUID("01995140-0000-7000-8000-000000000010"),
        now=now,
    )

    snapshot = message.model_dump(mode="json")
    assert set(snapshot) == {
        "id",
        "dialog_id",
        "sender_id",
        "client_message_id",
        "content",
        "position",
        "created_at",
    }
    original = deepcopy(snapshot)
    assert Message.model_validate(snapshot) == message
    assert Message.model_validate_json(message.model_dump_json()) == message
    assert snapshot == original
    assert message.is_sent_by(alice_id)
    assert message.text_value == "Independent message"

    legacy_snapshot = {
        **snapshot,
        "dialog_kind": "DIRECT",
        "recipient_id": str(alice_id),
    }
    before = deepcopy(legacy_snapshot)
    with pytest.raises(ValidationError):
        Message.model_validate(legacy_snapshot)
    assert legacy_snapshot == before
