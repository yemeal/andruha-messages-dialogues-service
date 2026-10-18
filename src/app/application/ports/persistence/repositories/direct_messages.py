from typing import Protocol
from uuid import UUID

from app.domain.aggregates.message import Message
from app.domain.value_objects.message_send_key import MessageSendKey


class DirectMessageRepositoryProtocol(Protocol):
    """Долговременное хранение сообщений личных и сохранённых диалогов.

    Обеспечивает LWT-гарантии уникальности MessageSendKey и строгую монотонность
    позиций сообщений в рамках диалога.
    """

    async def get_by_send_key(self, send_key: MessageSendKey) -> Message | None:
        """Поиск сообщения по составному ключу отправки (sender_id, client_message_id)."""
        ...

    async def get_last_position(self, dialog_id: UUID) -> int:
        """Текущая максимальная позиция в истории сообщений диалога (0 если сообщений нет)."""
        ...

    async def get_message_by_id(
        self, dialog_id: UUID, message_id: UUID
    ) -> Message | None:
        """Поиск сообщения диалога по идентификатору."""
        ...

    async def save_message(
        self, message: Message, *, idempotency_key: MessageSendKey
    ) -> Message:
        """Атомарно сохраняет сообщение и резервирует ключ отправки."""
        ...
