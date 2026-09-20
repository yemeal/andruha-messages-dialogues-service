from datetime import UTC, datetime
from functools import total_ordering
from typing import Annotated, Self

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.clock import utc_now
from app.domain.exceptions.base import InvalidDomainTimestampError
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
        if value.utcoffset() is None:
            raise InvalidDomainTimestampError()
        return value.astimezone(UTC)

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
            timestamp=timestamp if timestamp is not None else utc_now(),
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, MessageCheckpoint):
            return NotImplemented
        return self.position < other.position
