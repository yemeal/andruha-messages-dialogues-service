from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.dialogues.send_direct_message.command import (
    SendDirectMessageCommand,
)
from app.application.commands.dialogues.send_direct_message.result import (
    SendDirectMessageResult,
)
from app.application.dto.messages import MessageDTO
from app.application.exceptions.groups import (
    DialogNotFoundError,
    MessageSendConflictError,
)
from app.application.ports.objects.attachments import AttachmentVerifierProtocol
from app.application.ports.persistence.repositories.direct_dialogues import (
    DirectDialogRepositoryProtocol,
)
from app.application.ports.persistence.repositories.direct_messages import (
    DirectMessageRepositoryProtocol,
)
from app.domain.policies.message_posting import MessagePostingPolicy
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.domain.value_objects.message_send_key import MessageSendKey


class SendDirectMessageHandler:
    def __init__(
        self,
        direct_dialogs: DirectDialogRepositoryProtocol,
        direct_messages: DirectMessageRepositoryProtocol,
        attachments: AttachmentVerifierProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
    ) -> None:
        self._direct_dialogs = direct_dialogs
        self._direct_messages = direct_messages
        self._attachments = attachments
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, command: SendDirectMessageCommand
    ) -> SendDirectMessageResult:
        dialog = await self._direct_dialogs.get_by_id(command.dialog_id)
        if dialog is None:
            raise DialogNotFoundError(command.dialog_id)
        dialog.require_can_send(command.actor_id)

        client_id = ClientMessageId.from_uuid(command.client_message_id)
        content = MessageContent.from_parts(
            text=command.text, attachments=command.attachment_ids
        )
        send_key = MessageSendKey(
            sender_id=command.actor_id, client_message_id=client_id
        )

        existing = await self._direct_messages.get_by_send_key(send_key)
        if existing is not None:
            if (
                existing.dialog_id != command.dialog_id
                or existing.send_key != send_key
                or existing.content.attachments != content.attachments
                or (not existing.is_edited and existing.content != content)
            ):
                raise MessageSendConflictError()
            return SendDirectMessageResult(message=MessageDTO.from_domain(existing))

        if content.attachments:
            await self._attachments.require_ready(command.actor_id, content.attachments)

        last_pos = await self._direct_messages.get_last_position(command.dialog_id)
        message = MessagePostingPolicy.create_message(
            dialog=dialog,
            sender_id=command.actor_id,
            client_message_id=client_id,
            content=content,
            position=MessagePosition(dialog_id=command.dialog_id, value=last_pos + 1),
            message_id=self._ids(),
            now=self._clock(),
        )
        saved = await self._direct_messages.save_message(
            message, idempotency_key=send_key
        )
        return SendDirectMessageResult(message=MessageDTO.from_domain(saved))
