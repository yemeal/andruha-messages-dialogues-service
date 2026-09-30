from datetime import datetime
from typing import Self
from uuid import UUID

from app.application.dto.base import BaseDTO
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.message_checkpoint import MessageCheckpoint


class ReceiptCheckpointDTO(BaseDTO):
    position: int
    message_id: UUID
    timestamp: datetime

    @classmethod
    def from_domain(cls, checkpoint: MessageCheckpoint) -> Self:
        return cls(
            position=checkpoint.position.value,
            message_id=checkpoint.message_id,
            timestamp=checkpoint.timestamp,
        )


class ReceiptWatermarkDTO(BaseDTO):
    id: UUID
    dialog_id: UUID
    user_id: UUID
    delivered_through: ReceiptCheckpointDTO | None
    read_through: ReceiptCheckpointDTO | None
    version: int
    created_at: datetime
    updated_at: datetime | None

    @classmethod
    def from_domain(cls, receipt: ReceiptWatermark) -> Self:
        return cls(
            id=receipt.id,
            dialog_id=receipt.dialog_id,
            user_id=receipt.user_id,
            delivered_through=(
                ReceiptCheckpointDTO.from_domain(receipt.delivered_through)
                if receipt.delivered_through is not None
                else None
            ),
            read_through=(
                ReceiptCheckpointDTO.from_domain(receipt.read_through)
                if receipt.read_through is not None
                else None
            ),
            version=receipt.version,
            created_at=receipt.created_at,
            updated_at=receipt.updated_at,
        )
