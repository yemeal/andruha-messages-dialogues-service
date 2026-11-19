from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.ports.dto.outbox import OutboxMessage


class OutboxRepositoryProtocol(Protocol):
    """
    Durable lifecycle outbox-таблицы интеграционных событий Messages and Dialogues Service.
    """

    async def save_messages(self, messages: tuple[OutboxMessage, ...]) -> None:
        """
        Сохраняет пачку outbox-сообщений.
        """
        ...

    async def claim_batch(
        self,
        *,
        owner_token: UUID,
        claimed_at: datetime,
        claim_expires_at: datetime,
        limit: int,
    ) -> list[OutboxMessage]:
        """
        Берёт пачку сообщений в обработку воркером (переводит в CLAIMED).
        """
        ...

    async def finalize_published(
        self,
        message_id: UUID,
        *,
        owner_token: UUID,
        published_at: datetime,
    ) -> bool:
        """
        Помечает сообщение успешно опубликованным (SUCCESS, terminal_at=published_at).
        """
        ...

    async def schedule_retry(
        self,
        message_id: UUID,
        *,
        owner_token: UUID,
        available_at: datetime,
        error_class: str = "TransientPublishError",
    ) -> bool:
        """
        Планирует повторную попытку публикации (PENDING, available_at=available_at).
        """
        ...

    async def quarantine(
        self,
        message_id: UUID,
        *,
        owner_token: UUID,
        quarantined_at: datetime,
        error_class: str = "PermanentOutboxPublishError",
    ) -> bool:
        """
        Отправляет сообщение в карантин (QUARANTINED, terminal_at=quarantined_at).
        """
        ...
