from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.exceptions.messages import (
    WatermarkDialogMismatchError,
    WatermarkRecipientMismatchError,
)
from app.domain.protocols import ReceiptDialog
from app.domain.value_objects.message_checkpoint import MessageCheckpoint

if TYPE_CHECKING:
    from app.domain.aggregates.message import Message


class MessageDeliveryStatus(StrEnum):
    """
    Статус доставки сообщения с точки зрения получателя.

    - SENT: сообщение надёжно сохранено сервером.
    - DELIVERED: получатель подтвердил доставку до границы, включающей данное сообщение.
    - READ: получатель подтвердил прочтение до границы, включающей данное сообщение.
    """

    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"


class MessageDeliveryPolicy:
    """
    Чистая доменная политика вычисления статуса доставки сообщения по ватермарке получателя.
    """

    @staticmethod
    def calculate_status(
        message: Message,
        watermark: ReceiptWatermark | None = None,
        *,
        dialog: ReceiptDialog,
        recipient_id: UUID,
    ) -> MessageDeliveryStatus:
        """
        Вычисляет статус уже сохранённого сообщения по подтверждениям получателя.

        Durable сохранение — предусловие application: политика не обращается к БД.
        """
        if dialog.id != message.dialog_id or (
            watermark is not None and watermark.dialog_id != message.dialog_id
        ):
            raise WatermarkDialogMismatchError()

        dialog.require_message_access(
            sender_id=message.sender_id, reader_id=recipient_id
        )
        if watermark is not None and watermark.user_id != recipient_id:
            raise WatermarkRecipientMismatchError()

        if not dialog.supports_receipts:
            return MessageDeliveryStatus.SENT
        if message.is_sent_by(recipient_id):
            raise WatermarkRecipientMismatchError()
        if watermark is None:
            return MessageDeliveryStatus.SENT

        checkpoint = MessageCheckpoint.create(
            position=message.position,
            message_id=message.id,
            timestamp=message.created_at,
        )
        if watermark.is_read(checkpoint):
            return MessageDeliveryStatus.READ
        if watermark.is_delivered(checkpoint):
            return MessageDeliveryStatus.DELIVERED
        return MessageDeliveryStatus.SENT

    @classmethod
    def status_for(
        cls,
        message: Message,
        watermark: ReceiptWatermark | None = None,
        *,
        dialog: ReceiptDialog,
        recipient_id: UUID,
    ) -> MessageDeliveryStatus:
        """
        Псевдоним calculate_status для соответствия спецификации доменной модели.
        """
        return cls.calculate_status(
            message, watermark, dialog=dialog, recipient_id=recipient_id
        )
