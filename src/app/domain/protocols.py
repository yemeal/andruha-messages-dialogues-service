from datetime import datetime
from typing import Protocol
from uuid import UUID


class PostingDialog(Protocol):
    """Факты и правило диалога, необходимые для новой отправки."""

    @property
    def id(self) -> UUID: ...

    @property
    def created_at(self) -> datetime: ...

    def require_can_send(self, user_id: UUID) -> None:
        """Отказывает без изменения состояния, если пользователь не вправе писать."""
        ...


class ReceiptDialog(Protocol):
    """Доступ к истории и наличие подтверждений, независимо от типа диалога."""

    @property
    def id(self) -> UUID: ...

    @property
    def supports_receipts(self) -> bool: ...

    def require_message_access(self, *, sender_id: UUID, reader_id: UUID) -> None:
        """Проверяет текущий доступ читателя к сохранённому сообщению этого автора."""
        ...
