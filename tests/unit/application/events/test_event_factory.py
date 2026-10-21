from datetime import UTC, datetime
from uuid import uuid7

import pytest

from app.application.events.factory import EventFactory
from app.application.ports.dto.outbox import OutboxKind, OutboxStatus
from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.domain.value_objects.message_text import MessageText


@pytest.fixture
def sample_message() -> Message:
    dialog_id = uuid7()
    sender_id = uuid7()
    client_id = ClientMessageId.generate()
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)

    return Message.create(
        dialog_id=dialog_id,
        sender_id=sender_id,
        client_message_id=client_id,
        content=MessageContent(text=MessageText.from_str("Hello world!")),
        position=MessagePosition(dialog_id=dialog_id, value=1),
        message_id=uuid7(),
        now=now,
    )


def test_factory_creates_message_persisted_outbox_message(
    sample_message: Message,
) -> None:
    factory = EventFactory()
    correlation_id = uuid7()

    outbox_msg = factory.create_message_persisted(
        message=sample_message,
        correlation_id=correlation_id,
    )

    assert outbox_msg.kind is OutboxKind.EVENT
    assert outbox_msg.topic == "messages.events"
    assert outbox_msg.key == str(sample_message.sender_id)
    assert outbox_msg.type == "message.persisted.v1"
    assert outbox_msg.status is OutboxStatus.PENDING

    payload = outbox_msg.payload
    assert payload["eventType"] == "message.persisted.v1"
    assert payload["correlationId"] == str(correlation_id)
    assert payload["payload"]["targetUserId"] == str(sample_message.sender_id)
    assert payload["payload"]["clientMessageId"] == str(
        sample_message.client_message_id.value
    )
    assert payload["payload"]["message"]["messageId"] == str(sample_message.id)
    assert payload["payload"]["message"]["text"] == "Hello world!"


def test_factory_creates_message_created_outbox_messages(
    sample_message: Message,
) -> None:
    factory = EventFactory()
    recipient1 = uuid7()
    recipient2 = uuid7()
    correlation_id = uuid7()

    messages = factory.create_message_created_batch(
        message=sample_message,
        recipient_ids=(recipient1, recipient2),
        correlation_id=correlation_id,
    )

    assert len(messages) == 2
    keys = {m.key for m in messages}
    assert keys == {str(recipient1), str(recipient2)}

    for m in messages:
        assert m.kind is OutboxKind.EVENT
        assert m.topic == "messages.events"
        assert m.type == "message.created.v1"
        assert m.status is OutboxStatus.PENDING
        assert m.payload["eventType"] == "message.created.v1"
        assert m.payload["payload"]["message"]["messageId"] == str(sample_message.id)


def test_factory_creates_receipt_watermark_advanced_outbox_message() -> None:
    factory = EventFactory()
    dialog_id = uuid7()
    author_id = uuid7()
    through_msg_id = uuid7()
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    correlation_id = uuid7()

    outbox_msg = factory.create_receipt_watermark_advanced(
        dialog_id=dialog_id,
        target_user_id=author_id,
        kind="READ",
        through_message_id=through_msg_id,
        through_message_time=now,
        status_version=3,
        correlation_id=correlation_id,
    )

    assert outbox_msg.kind is OutboxKind.EVENT
    assert outbox_msg.topic == "receipts.events"
    assert outbox_msg.key == str(author_id)
    assert outbox_msg.type == "receipt.watermark_advanced.v1"
    assert outbox_msg.payload["payload"]["statusVersion"] == 3
    assert outbox_msg.payload["payload"]["kind"] == "READ"


def test_factory_creates_message_rejected_outbox_message() -> None:
    factory = EventFactory()
    target_user_id = uuid7()
    client_message_id = uuid7()
    dialog_id = uuid7()
    correlation_id = uuid7()

    outbox_msg = factory.create_message_rejected(
        target_user_id=target_user_id,
        client_message_id=client_message_id,
        dialog_id=dialog_id,
        code="message.send_conflict",
        correlation_id=correlation_id,
    )

    assert outbox_msg.kind is OutboxKind.EVENT
    assert outbox_msg.topic == "messages.events"
    assert outbox_msg.key == str(target_user_id)
    assert outbox_msg.type == "message.rejected.v1"
    assert outbox_msg.payload["payload"]["code"] == "message.send_conflict"
    assert outbox_msg.payload["payload"]["retryable"] is False
