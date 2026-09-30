from enum import StrEnum
from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.commands.groups.advance_receipt.result import (
    AdvanceGroupReceiptResult,
)


class ReceiptKind(StrEnum):
    DELIVERED = "DELIVERED"
    READ = "READ"


class AdvanceGroupReceiptCommand(BaseCommand[AdvanceGroupReceiptResult]):
    dialog_id: UUID
    actor_id: UUID
    kind: ReceiptKind
    through_message_id: UUID
