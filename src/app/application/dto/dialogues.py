from datetime import datetime
from typing import Self
from uuid import UUID

from app.application.dto.base import BaseDTO
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog


class DirectDialogDTO(BaseDTO):
    id: UUID
    participants: tuple[UUID, UUID]
    created_at: datetime

    @classmethod
    def from_domain(cls, dialog: DirectDialog) -> Self:
        return cls(
            id=dialog.id,
            participants=dialog.as_tuple,
            created_at=dialog.created_at,
        )


class SavedDialogDTO(BaseDTO):
    id: UUID
    user_id: UUID
    created_at: datetime

    @classmethod
    def from_domain(cls, dialog: SavedDialog) -> Self:
        return cls.model_validate(dialog)
