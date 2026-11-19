from typing import Protocol
from uuid import UUID

from app.application.dto.reading import DialogBatch, DialogSummary, SyncBatch
from app.domain.aggregates.message import Message


class MessageReadsProtocol(Protocol):
    async def history(
        self, dialog_id: UUID, *, after: int, through: int | None, limit: int
    ) -> tuple[tuple[Message, ...], int]: ...

    async def get_message_by_id(
        self, dialog_id: UUID, message_id: UUID
    ) -> Message | None: ...


class UserReadsProtocol(Protocol):
    async def get_dialog(
        self, user_id: UUID, dialog_id: UUID
    ) -> DialogSummary | None: ...

    async def sync(
        self, user_id: UUID, *, after: int, through: int | None, limit: int
    ) -> SyncBatch: ...

    async def dialogs(
        self, user_id: UUID, *, after: int, through: int | None, limit: int
    ) -> DialogBatch: ...
