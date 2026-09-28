from functools import total_ordering
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.domain.base import DomainModel
from app.domain.exceptions.messages import PositionDialogMismatchError


@total_ordering
class MessagePosition(DomainModel):
    """
    Монотонная позиция сообщения в истории одного диалога.
    """

    dialog_id: Annotated[
        UUID,
        Field(description="Диалог, внутри которого упорядочены сообщения."),
    ]
    value: Annotated[
        int,
        Field(
            gt=0,
            strict=True,
            description="Положительное целое число монотонного порядка.",
        ),
    ]

    def __int__(self) -> int:
        return self.value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, MessagePosition):
            return NotImplemented
        if self.dialog_id != other.dialog_id:
            raise PositionDialogMismatchError()
        return self.value < other.value
