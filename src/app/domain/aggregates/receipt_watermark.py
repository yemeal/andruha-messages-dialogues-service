from datetime import datetime
from typing import Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field, model_validator

from app.domain.base import VersionedMutableEntity
from app.domain.clock import ensure_utc
from app.domain.exceptions.receipts import ReadCheckpointExceedsDeliveredError
from app.domain.value_objects.message_checkpoint import MessageCheckpoint
from app.domain.value_objects.message_position import MessagePosition


class ReceiptWatermark(VersionedMutableEntity):
    """
    Подтверждённая граница доставки и прочтения входящих сообщений участника в диалоге.
    """

    dialog_id: Annotated[
        UUID,
        Field(
            description="Идентификатор диалога (UUID).",
        ),
    ]
    user_id: Annotated[
        UUID,
        Field(
            description="Идентификатор участника-получателя входящих сообщений (UUID).",
        ),
    ]
    delivered_through: Annotated[
        MessageCheckpoint | None,
        Field(
            default=None,
            description="Граница подтверждённой доставки входящих сообщений.",
        ),
    ]
    read_through: Annotated[
        MessageCheckpoint | None,
        Field(
            default=None,
            description="Граница подтверждённого прочтения входящих сообщений.",
        ),
    ]

    @model_validator(mode="after")
    def _validate_watermark_invariants(self) -> Self:
        """
        Гарантирует инвариант: прочтение не может опережать доставку (read <= delivered).
        """
        if self.read_through is not None and (
            self.delivered_through is None or self.read_through > self.delivered_through
        ):
            raise ReadCheckpointExceedsDeliveredError()
        return self

    @classmethod
    def create_empty(
        cls,
        *,
        dialog_id: UUID,
        user_id: UUID,
        watermark_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        """
        Создаёт начальное пустое состояние ватермарки.
        """
        instant = ensure_utc(now)
        return cls(
            id=watermark_id if watermark_id is not None else uuid7(),
            dialog_id=dialog_id,
            user_id=user_id,
            delivered_through=None,
            read_through=None,
            created_at=instant,
            updated_at=instant,
            version=1,
        )

    def is_delivered(self, target: MessagePosition | MessageCheckpoint | int) -> bool:
        """
        Проверяет, входит ли позиция сообщения или чекпоинт в подтверждённую границу доставки.
        """
        if self.delivered_through is None:
            return False
        if isinstance(target, MessageCheckpoint):
            pos = target.position
        elif isinstance(target, MessagePosition):
            pos = target
        else:
            pos = MessagePosition(value=target)
        return pos <= self.delivered_through.position

    def is_read(self, target: MessagePosition | MessageCheckpoint | int) -> bool:
        """
        Проверяет, входит ли позиция сообщения или чекпоинт в подтверждённую границу прочтения.
        """
        if self.read_through is None:
            return False
        if isinstance(target, MessageCheckpoint):
            pos = target.position
        elif isinstance(target, MessagePosition):
            pos = target
        else:
            pos = MessagePosition(value=target)
        return pos <= self.read_through.position

    def advance_delivered(self, checkpoint: MessageCheckpoint, now: datetime) -> bool:
        """
        Сдвигает границу ДОСТАВКИ входящих сообщений.

        Если чекпоинт уже доставлен — это запоздалый/повторный ACK,
        метод возвращает False (no-op), версия и updated_at не меняются.
        """
        if self.is_delivered(checkpoint):
            return False

        return self._apply_changes(
            now=now,
            delivered_through=checkpoint,
        )

    def advance_read(self, checkpoint: MessageCheckpoint, now: datetime) -> bool:
        """
        Сдвигает границу ПРОЧТЕНИЯ входящих сообщений.
        Автоматически подтягивает границу доставки: delivered_through = max(delivered, read).

        Если чекпоинт уже прочитан — это повторный ACK,
        метод возвращает False (no-op), версия и updated_at не меняются.
        """
        if self.is_read(checkpoint):
            return False

        new_delivered = (
            self.delivered_through if self.is_delivered(checkpoint) else checkpoint
        )
        return self._apply_changes(
            now=now,
            read_through=checkpoint,
            delivered_through=new_delivered,
        )
