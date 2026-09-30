from typing import ClassVar

from app.domain.exceptions.base import DomainError
from app.domain.limits import MAX_MESSAGE_TEXT_LENGTH


class InvalidClientMessageIdVersionError(DomainError):
    """Клиентский токен идемпотентности обязан быть UUIDv7."""

    default_message: ClassVar[str] = "Client message ID must be a UUIDv7"


class InvalidMessageTextError(DomainError):
    """Текст сообщения должен быть непустым и не превышать установленный лимит."""

    default_message: ClassVar[str] = (
        f"Message text must be non-empty and between 1 and {MAX_MESSAGE_TEXT_LENGTH} code points"
    )


class EmptyMessageContentError(DomainError):
    """Содержимое сообщения не может быть пустым."""

    default_message: ClassVar[str] = "Message content cannot be empty"


class NotMessageAuthorError(DomainError):
    """Редактировать текст сообщения вправе только его автор."""

    default_message: ClassVar[str] = "Only the message author can edit its text"


class InvalidMessageEditMetadataError(DomainError):
    """Версия сообщения и наличие времени редактирования должны согласовываться."""

    default_message: ClassVar[str] = (
        "Message edit version and timestamp are inconsistent"
    )


class InvalidMessageAttachmentsError(DomainError):
    """Набор вложений нарушает лимит или содержит один объект несколько раз."""

    default_message: ClassVar[str] = "Message attachments are invalid"


class MessageCreatedAtPrecedesDialogError(DomainError):
    """Время создания сообщения не может предшествовать времени создания диалога."""

    default_message: ClassVar[str] = (
        "Message creation time cannot precede dialog creation time"
    )


class PositionDialogMismatchError(DomainError):
    """Позиции разных диалогов нельзя сравнивать или присваивать сообщению."""

    default_message: ClassVar[str] = "Message position belongs to another dialog"


class WatermarkDialogMismatchError(DomainError):
    """Попытка рассчитать статус сообщения по ватермарке чужого диалога."""

    default_message: ClassVar[str] = (
        "Watermark dialog ID does not match message dialog ID"
    )


class WatermarkRecipientMismatchError(DomainError):
    """Попытка рассчитать статус сообщения по ватермарке другого пользователя."""

    default_message: ClassVar[str] = (
        "Watermark user ID does not match the requested recipient"
    )
