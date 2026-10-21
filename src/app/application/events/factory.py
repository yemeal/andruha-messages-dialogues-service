from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid7

from app.application.events.models import (
    AttachmentSnapshotDTO,
    EventEnvelope,
    MessageCreatedPayload,
    MessagePersistedPayload,
    MessageRejectedPayload,
    MessageSnapshotDTO,
    ReceiptWatermarkAdvancedPayload,
)
from app.application.ports.dto.outbox import OutboxKind, OutboxMessage, OutboxStatus
from app.domain.aggregates.message import Message
from app.domain.clock import utc_now


class EventFactory:
    """
    Фабрика интеграционных Outbox-событий по межсервисным контрактам Andruha.
    """

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        ids: Callable[[], UUID] = uuid7,
        producer: str = "andruha-messages-dialogues-service",
    ) -> None:
        self._clock = clock
        self._ids = ids
        self._producer = producer

    def create_message_persisted(
        self,
        *,
        message: Message,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        attachments: tuple[AttachmentSnapshotDTO, ...] = (),
        occurred_at: datetime | None = None,
    ) -> OutboxMessage:
        now = occurred_at or self._clock()
        msg_snapshot = MessageSnapshotDTO(
            message_id=message.id,
            dialog_id=message.dialog_id,
            sender_id=message.sender_id,
            sent_at=message.created_at,
            text=message.text_value,
            attachments=attachments,
        )
        payload = MessagePersistedPayload(
            target_user_id=message.sender_id,
            client_message_id=message.client_message_id.value,
            message=msg_snapshot,
        )
        envelope = EventEnvelope(
            event_id=self._ids(),
            event_type="message.persisted.v1",
            schema_version=1,
            occurred_at=now,
            producer=self._producer,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
        )
        return OutboxMessage(
            id=self._ids(),
            kind=OutboxKind.EVENT,
            topic="messages.events",
            key=str(message.sender_id),
            type="message.persisted.v1",
            payload=envelope.model_dump(mode="json", by_alias=True),
            status=OutboxStatus.PENDING,
            created_at=now,
            available_at=now,
        )

    def create_message_created_batch(
        self,
        *,
        message: Message,
        recipient_ids: tuple[UUID, ...],
        correlation_id: UUID,
        causation_id: UUID | None = None,
        attachments: tuple[AttachmentSnapshotDTO, ...] = (),
        occurred_at: datetime | None = None,
    ) -> tuple[OutboxMessage, ...]:
        now = occurred_at or self._clock()
        msg_snapshot = MessageSnapshotDTO(
            message_id=message.id,
            dialog_id=message.dialog_id,
            sender_id=message.sender_id,
            sent_at=message.created_at,
            text=message.text_value,
            attachments=attachments,
        )
        events: list[OutboxMessage] = []
        for recipient_id in recipient_ids:
            payload = MessageCreatedPayload(
                target_user_id=recipient_id,
                message=msg_snapshot,
            )
            envelope = EventEnvelope(
                event_id=self._ids(),
                event_type="message.created.v1",
                schema_version=1,
                occurred_at=now,
                producer=self._producer,
                correlation_id=correlation_id,
                causation_id=causation_id,
                payload=payload,
            )
            events.append(
                OutboxMessage(
                    id=self._ids(),
                    kind=OutboxKind.EVENT,
                    topic="messages.events",
                    key=str(recipient_id),
                    type="message.created.v1",
                    payload=envelope.model_dump(mode="json", by_alias=True),
                    status=OutboxStatus.PENDING,
                    created_at=now,
                    available_at=now,
                )
            )
        return tuple(events)

    def create_receipt_watermark_advanced(
        self,
        *,
        dialog_id: UUID,
        target_user_id: UUID,
        kind: Literal["DELIVERED", "READ"],
        through_message_id: UUID,
        through_message_time: datetime,
        status_version: int,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> OutboxMessage:
        now = occurred_at or self._clock()
        payload = ReceiptWatermarkAdvancedPayload(
            target_user_id=target_user_id,
            dialog_id=dialog_id,
            kind=kind,
            through_message_id=through_message_id,
            through_message_time=through_message_time,
            status_version=status_version,
        )
        envelope = EventEnvelope(
            event_id=self._ids(),
            event_type="receipt.watermark_advanced.v1",
            schema_version=1,
            occurred_at=now,
            producer=self._producer,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
        )
        return OutboxMessage(
            id=self._ids(),
            kind=OutboxKind.EVENT,
            topic="receipts.events",
            key=str(target_user_id),
            type="receipt.watermark_advanced.v1",
            payload=envelope.model_dump(mode="json", by_alias=True),
            status=OutboxStatus.PENDING,
            created_at=now,
            available_at=now,
        )

    def create_message_rejected(
        self,
        *,
        target_user_id: UUID,
        client_message_id: UUID,
        dialog_id: UUID,
        code: str,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> OutboxMessage:
        now = occurred_at or self._clock()
        payload = MessageRejectedPayload(
            target_user_id=target_user_id,
            client_message_id=client_message_id,
            dialog_id=dialog_id,
            code=code,
        )
        envelope = EventEnvelope(
            event_id=self._ids(),
            event_type="message.rejected.v1",
            schema_version=1,
            occurred_at=now,
            producer=self._producer,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
        )
        return OutboxMessage(
            id=self._ids(),
            kind=OutboxKind.EVENT,
            topic="messages.events",
            key=str(target_user_id),
            type="message.rejected.v1",
            payload=envelope.model_dump(mode="json", by_alias=True),
            status=OutboxStatus.PENDING,
            created_at=now,
            available_at=now,
        )
