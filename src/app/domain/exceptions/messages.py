from typing import ClassVar

from app.domain.exceptions.base import DomainError


class SenderRecipientSameUserError(DomainError):
    """Отправитель и получатель не могут быть одним и тем же пользователем."""

    default_message: ClassVar[str] = "Sender and recipient cannot be the same user"


class InvalidClientMessageIdVersionError(DomainError):
    """Клиентский токен идемпотентности обязан быть UUIDv7."""

    default_message: ClassVar[str] = "Client message ID must be a UUIDv7"


class InvalidMessageTextError(DomainError):
    """Текст сообщения должен быть непустым и содержать от 1 до 4096 символов."""

    default_message: ClassVar[str] = (
        "Message text must be non-empty and between 1 and 4096 code points"
    )


class EmptyMessageContentError(DomainError):
    """Содержимое сообщения не может быть пустым."""

    default_message: ClassVar[str] = "Message content cannot be empty"


class MessageCreatedAtPrecedesDialogError(DomainError):
    """Время создания сообщения не может предшествовать времени создания диалога."""

    default_message: ClassVar[str] = (
        "Message creation time cannot precede dialog creation time"
    )


class WatermarkDialogMismatchError(DomainError):
    """Попытка рассчитать статус сообщения по ватермарке чужого диалога."""

    default_message: ClassVar[str] = (
        "Watermark dialog ID does not match message dialog ID"
    )


class WatermarkRecipientMismatchError(DomainError):
    """Попытка рассчитать статус сообщения по ватермарке другого пользователя."""

    default_message: ClassVar[str] = (
        "Watermark user ID does not match message recipient ID"
    )
