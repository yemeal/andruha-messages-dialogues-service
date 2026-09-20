from functools import total_ordering
from typing import Annotated

from pydantic import Field

from app.domain.base import DomainModel


@total_ordering
class MessagePosition(DomainModel):
    """
    Монотонная позиция сообщения в истории диалога (HLC).
    """

    value: Annotated[
        int,
        Field(
            gt=0,
            description="Положительное целое число монотонного порядка.",
        ),
    ]

    def __int__(self) -> int:
        return self.value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, MessagePosition):
            return NotImplemented
        return self.value < other.value
