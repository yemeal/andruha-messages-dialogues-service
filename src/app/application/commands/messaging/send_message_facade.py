from uuid import UUID

from pydantic import Field

from app.application.commands.base import BaseCommand
from app.application.commands.dialogues.send_direct_message.command import (
    SendDirectMessageCommand,
)
from app.application.commands.dialogues.send_direct_message.handler import (
    SendDirectMessageHandler,
)
from app.application.commands.dialogues.send_saved_message.command import (
    SendSavedMessageCommand,
)
from app.application.commands.dialogues.send_saved_message.handler import (
    SendSavedMessageHandler,
)
from app.application.commands.groups.send_message.command import (
    SendGroupMessageCommand,
)
from app.application.commands.groups.send_message.handler import (
    SendGroupMessageHandler,
)
from app.application.dto.base import BaseDTO
from app.application.dto.messages import MessageDTO
from app.application.exceptions.dialogues import UnsupportedDialogKindError
from app.application.exceptions.groups import DialogNotFoundError
from app.application.ports.persistence.repositories.dialog_lookup import (
    DialogKind,
    DialogLookupProtocol,
)


class SendMessageFacadeResult(BaseDTO):
    message: MessageDTO
    dialog_kind: DialogKind


class SendMessageFacadeCommand(BaseCommand[SendMessageFacadeResult]):
    """Единая команда отправки сообщения с маршрутизацией по dialog_id."""

    dialog_id: UUID
    actor_id: UUID
    client_message_id: UUID = Field(
        description="UUIDv7 одной отправки; новый для нового сообщения, прежний для retry."
    )
    text: str | None = Field(default=None)
    attachment_ids: tuple[UUID, ...] = Field(default=())


class SendMessageFacadeHandler:
    def __init__(
        self,
        dialog_lookup: DialogLookupProtocol,
        send_direct: SendDirectMessageHandler,
        send_group: SendGroupMessageHandler,
        send_saved: SendSavedMessageHandler,
    ) -> None:
        self._dialog_lookup = dialog_lookup
        self._send_direct = send_direct
        self._send_group = send_group
        self._send_saved = send_saved

    async def __call__(
        self, command: SendMessageFacadeCommand
    ) -> SendMessageFacadeResult:
        kind = await self._dialog_lookup.get_dialog_kind(command.dialog_id)
        if kind is None:
            raise DialogNotFoundError(command.dialog_id)

        if kind is DialogKind.DIRECT:
            result = await self._send_direct(
                SendDirectMessageCommand(
                    dialog_id=command.dialog_id,
                    actor_id=command.actor_id,
                    client_message_id=command.client_message_id,
                    text=command.text,
                    attachment_ids=command.attachment_ids,
                )
            )
            return SendMessageFacadeResult(message=result.message, dialog_kind=kind)

        if kind is DialogKind.GROUP:
            result = await self._send_group(
                SendGroupMessageCommand(
                    dialog_id=command.dialog_id,
                    actor_id=command.actor_id,
                    client_message_id=command.client_message_id,
                    text=command.text,
                    attachment_ids=command.attachment_ids,
                )
            )
            return SendMessageFacadeResult(message=result.message, dialog_kind=kind)

        if kind is DialogKind.SAVED:
            result = await self._send_saved(
                SendSavedMessageCommand(
                    dialog_id=command.dialog_id,
                    actor_id=command.actor_id,
                    client_message_id=command.client_message_id,
                    text=command.text,
                    attachment_ids=command.attachment_ids,
                )
            )
            return SendMessageFacadeResult(message=result.message, dialog_kind=kind)

        raise UnsupportedDialogKindError(str(kind))
