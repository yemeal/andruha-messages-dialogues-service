from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest

from app.application.events.models import (
    AttachmentSnapshotDTO,
    EventEnvelope,
    MessageCreatedPayload,
    MessagePersistedPayload,
    MessageRejectedPayload,
    MessageSnapshotDTO,
    ReceiptWatermarkAdvancedPayload,
)


def test_message_persisted_event_envelope_creation() -> None:
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    correlation_id = uuid7()
    causation_id = uuid7()
    target_user_id = uuid7()
    client_message_id = uuid7()
    message_id = uuid7()
    dialog_id = uuid7()

    msg_snapshot = MessageSnapshotDTO(
        message_id=message_id,
        dialog_id=dialog_id,
        sender_id=target_user_id,
        sent_at=now,
        text="Hello!",
        attachments=(),
    )
    payload = MessagePersistedPayload(
        target_user_id=target_user_id,
        client_message_id=client_message_id,
        message=msg_snapshot,
    )
    envelope = EventEnvelope(
        event_type="message.persisted.v1",
        schema_version=1,
        occurred_at=now,
        producer="andruha-messages-dialogues-service",
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=payload,
    )

    assert isinstance(envelope.event_id, UUID)
    assert envelope.event_id.version == 7
    assert envelope.event_type == "message.persisted.v1"
    assert envelope.schema_version == 1
    assert envelope.occurred_at == now
    assert envelope.producer == "andruha-messages-dialogues-service"
    assert envelope.correlation_id == correlation_id
    assert envelope.causation_id == causation_id

    # Check serialized format for camelCase
    dumped = envelope.model_dump(mode="json", by_alias=True)
    assert dumped["eventId"] == str(envelope.event_id)
    assert dumped["eventType"] == "message.persisted.v1"
    assert dumped["schemaVersion"] == 1
    assert dumped["occurredAt"] == "2026-10-22T12:00:00Z"
    assert dumped["producer"] == "andruha-messages-dialogues-service"
    assert dumped["correlationId"] == str(correlation_id)
    assert dumped["causationId"] == str(causation_id)
    assert dumped["payload"]["targetUserId"] == str(target_user_id)
    assert dumped["payload"]["clientMessageId"] == str(client_message_id)
    assert dumped["payload"]["message"]["messageId"] == str(message_id)
    assert dumped["payload"]["message"]["dialogId"] == str(dialog_id)
    assert dumped["payload"]["message"]["senderId"] == str(target_user_id)
    assert dumped["payload"]["message"]["text"] == "Hello!"
    assert dumped["payload"]["message"]["attachments"] == []


def test_message_created_event_envelope_with_attachments() -> None:
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    correlation_id = uuid7()
    recipient_id = uuid7()
    sender_id = uuid7()
    message_id = uuid7()
    dialog_id = uuid7()
    object_id = uuid7()

    att = AttachmentSnapshotDTO(
        object_id=object_id,
        media_type="image/png",
        size_bytes=1024,
        sha256_base64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    msg_snapshot = MessageSnapshotDTO(
        message_id=message_id,
        dialog_id=dialog_id,
        sender_id=sender_id,
        sent_at=now,
        text=None,
        attachments=(att,),
    )
    payload = MessageCreatedPayload(
        target_user_id=recipient_id,
        message=msg_snapshot,
    )
    envelope = EventEnvelope(
        event_type="message.created.v1",
        occurred_at=now,
        correlation_id=correlation_id,
        payload=payload,
    )

    dumped = envelope.model_dump(mode="json", by_alias=True)
    assert dumped["eventType"] == "message.created.v1"
    assert dumped["payload"]["targetUserId"] == str(recipient_id)
    assert dumped["payload"]["message"]["text"] is None
    assert len(dumped["payload"]["message"]["attachments"]) == 1
    assert dumped["payload"]["message"]["attachments"][0]["objectId"] == str(object_id)
    assert dumped["payload"]["message"]["attachments"][0]["mediaType"] == "image/png"
    assert dumped["payload"]["message"]["attachments"][0]["sizeBytes"] == 1024


def test_receipt_watermark_advanced_payload() -> None:
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    dialog_id = uuid7()
    author_id = uuid7()
    through_msg_id = uuid7()

    payload = ReceiptWatermarkAdvancedPayload(
        target_user_id=author_id,
        dialog_id=dialog_id,
        kind="READ",
        through_message_id=through_msg_id,
        through_message_time=now,
        status_version=5,
    )
    dumped = payload.model_dump(mode="json", by_alias=True)
    assert dumped["targetUserId"] == str(author_id)
    assert dumped["dialogId"] == str(dialog_id)
    assert dumped["kind"] == "READ"
    assert dumped["throughMessageId"] == str(through_msg_id)
    assert dumped["statusVersion"] == 5


def test_message_rejected_payload_code_validation() -> None:
    sender_id = uuid7()
    client_id = uuid7()
    dialog_id = uuid7()

    payload = MessageRejectedPayload(
        target_user_id=sender_id,
        client_message_id=client_id,
        dialog_id=dialog_id,
        code="message.send_conflict",
    )
    assert payload.retryable is False

    with pytest.raises(ValueError, match="Invalid rejection code pattern"):
        MessageRejectedPayload(
            target_user_id=sender_id,
            client_message_id=client_id,
            dialog_id=dialog_id,
            code="INVALID CODE!",
        )
