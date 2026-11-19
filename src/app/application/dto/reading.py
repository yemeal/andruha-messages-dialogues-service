from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.application.dto.base import BaseDTO
from app.application.dto.messages import MessageDTO


class DialogSummary(BaseDTO):
    id: UUID
    kind: Literal["DIRECT", "SAVED"]
    participant_ids: tuple[UUID, ...]
    created_at: datetime
    last_position: int = Field(default=0)
    last_message: MessageDTO | None = Field(default=None)


class SyncEntry(BaseDTO):
    sequence: int
    event_id: UUID
    type: str
    dialog_id: UUID
    message: MessageDTO | None = Field(default=None)


class SyncBatch(BaseDTO):
    items: tuple[SyncEntry, ...]
    through: int


class DialogBatch(BaseDTO):
    items: tuple[DialogSummary, ...]
    through: int
    upper: int
