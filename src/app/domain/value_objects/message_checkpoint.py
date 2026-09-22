from datetime import datetime
from functools import total_ordering
from typing import Annotated, Self

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.clock import ensure_utc
from app.domain.value_objects.message_position import MessagePosition


@total_ordering
class MessageCheckpoint(DomainModel):
    """
    Точка отсечки в истории диалога.
    """

    position: Annotated[
        MessagePosition,
        Field(description="Позиция сообщения."),
    ]
    timestamp: Annotated[
        datetime,
        Field(description="UTC время фиксации чекпоинта."),
    ]

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @classmethod
    def create(
        cls,
        *,
        position: MessagePosition | int,
        timestamp: datetime | None = None,
    ) -> Self:
        """
        Фабричный метод создания чекпоинта.
        """
        pos = MessagePosition(value=position) if isinstance(position, int) else position
        return cls(
            position=pos,
            timestamp=ensure_utc(timestamp),
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, MessageCheckpoint):
            return NotImplemented
        return self.position < other.position
