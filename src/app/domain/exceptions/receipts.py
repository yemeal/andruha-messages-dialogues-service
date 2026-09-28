from typing import ClassVar

from app.domain.exceptions.base import DomainError


class ReadCheckpointExceedsDeliveredError(DomainError):
    """Граница прочтения не может опережать границу доставки."""

    default_message: ClassVar[str] = (
        "Read checkpoint cannot exceed delivered checkpoint"
    )


class CheckpointMessageMismatchError(DomainError):
    """Одна позиция диалога не может обозначать разные сообщения."""

    default_message: ClassVar[str] = "Checkpoint position identifies another message"


class ReceiptActorMismatchError(DomainError):
    """Подтверждение может выполнить только владелец watermark."""

    default_message: ClassVar[str] = "Receipt actor does not own this watermark"


class ReceiptDialogMismatchError(DomainError):
    """Подтверждение относится к другому диалогу."""

    default_message: ClassVar[str] = "Receipt belongs to another dialog"


class NotIncomingMessageError(DomainError):
    """Подтверждать можно только входящее сообщение."""

    default_message: ClassVar[str] = "Only an incoming message can be acknowledged"
