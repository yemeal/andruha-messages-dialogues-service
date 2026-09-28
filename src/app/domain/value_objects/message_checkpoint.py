from datetime import datetime
from functools import total_ordering
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.clock import ensure_utc
from app.domain.exceptions.receipts import CheckpointMessageMismatchError
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
    message_id: Annotated[
        UUID,
        Field(description="Сообщение на этой позиции."),
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
        position: MessagePosition,
        message_id: UUID,
        timestamp: datetime | None = None,
    ) -> Self:
        """
        Фабричный метод создания чекпоинта.
        """
        return cls(
            position=position,
            message_id=message_id,
            timestamp=ensure_utc(timestamp),
        )

    @property
    def dialog_id(self) -> UUID:
        return self.position.dialog_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MessageCheckpoint):
            return NotImplemented
        return (self.position, self.message_id) == (other.position, other.message_id)

    def __hash__(self) -> int:
        return hash((self.position, self.message_id))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, MessageCheckpoint):
            return NotImplemented
        if self.position == other.position and self.message_id != other.message_id:
            raise CheckpointMessageMismatchError()
        return self.position < other.position
