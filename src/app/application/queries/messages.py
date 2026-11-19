"""Authorization and read coordination, independent of HTTP and Cassandra."""

from uuid import UUID

from app.application.dto.messages import MessageDTO
from app.application.dto.reading import DialogSummary
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import DialogNotFoundError, MessageNotFoundError
from app.application.ports.persistence.repositories.direct_dialogues import (
    DirectDialogRepositoryProtocol,
)
from app.application.ports.persistence.repositories.saved_dialogues import (
    SavedDialogRepositoryProtocol,
)
from app.application.ports.reading import MessageReadsProtocol, UserReadsProtocol
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog


class MessageQueries:
    def __init__(
        self,
        direct: DirectDialogRepositoryProtocol,
        saved: SavedDialogRepositoryProtocol,
        messages: MessageReadsProtocol,
        users: UserReadsProtocol,
    ) -> None:
        self.direct = direct
        self.saved = saved
        self.messages = messages
        self.users = users

    async def require_dialog(
        self, actor_id: UUID, dialog_id: UUID
    ) -> DirectDialog | SavedDialog:
        dialog = await self.direct.get_by_id(dialog_id) or await self.saved.get_by_id(
            dialog_id
        )
        if dialog is None:
            raise DialogNotFoundError(dialog_id)
        dialog.require_can_read(actor_id)
        return dialog

    async def history(
        self,
        actor_id: UUID,
        dialog_id: UUID,
        *,
        after: int,
        through: int | None,
        limit: int,
    ) -> tuple[tuple[MessageDTO, ...], int]:
        await self.require_dialog(actor_id, dialog_id)
        items, upper = await self.messages.history(
            dialog_id, after=after, through=through, limit=limit
        )
        return tuple(MessageDTO.from_domain(item) for item in items), upper

    async def detail(self, actor_id: UUID, dialog_id: UUID) -> DialogSummary:
        await self.require_dialog(actor_id, dialog_id)
        result = await self.users.get_dialog(actor_id, dialog_id)
        if result is None:
            raise StorageUnavailableError("Dialog projection is incomplete")
        return result

    async def point(
        self, actor_id: UUID, dialog_id: UUID, message_id: UUID
    ) -> MessageDTO:
        await self.require_dialog(actor_id, dialog_id)
        message = await self.messages.get_message_by_id(dialog_id, message_id)
        if message is None:
            raise MessageNotFoundError(message_id)
        return MessageDTO.from_domain(message)
