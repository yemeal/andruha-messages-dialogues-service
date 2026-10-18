from enum import StrEnum
from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.commands.dialogues.advance_direct_receipt.result import (
    AdvanceDirectReceiptResult,
)


class ReceiptKind(StrEnum):
    DELIVERED = "DELIVERED"
    READ = "READ"


class AdvanceDirectReceiptCommand(BaseCommand[AdvanceDirectReceiptResult]):
    """Команда продвижения границы доставки или прочтения в 1:1 личном диалоге."""

    dialog_id: UUID
    actor_id: UUID
    kind: ReceiptKind
    through_message_id: UUID
