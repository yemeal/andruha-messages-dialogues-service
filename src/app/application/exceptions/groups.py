from uuid import UUID

from app.application.exceptions.base import ApplicationError


class DialogNotFoundError(ApplicationError):
    def __init__(self, dialog_id: UUID) -> None:
        self.dialog_id = dialog_id
        super().__init__(f"Dialog {dialog_id} was not found")


class ConcurrentModificationError(ApplicationError):
    """Исчерпан предел повторов после подтверждённых конфликтов ревизии."""


class MessageNotFoundError(ApplicationError):
    def __init__(self, message_id: UUID) -> None:
        self.message_id = message_id
        super().__init__(f"Persisted message {message_id} was not found in dialog")


class MessageSendConflictError(ApplicationError):
    """Клиентский ключ отправки уже обозначает другое содержимое."""
