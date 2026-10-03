from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.commands.groups.send_message.result import SendGroupMessageResult
from app.application.dto.messages import MessageDTO
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    DialogNotFoundError,
    GroupReadConflictError,
    MessageSendConflictError,
)
from app.application.ports.objects.attachments import AttachmentVerifierProtocol
from app.application.ports.persistence.repositories.group_commands import (
    GroupMessageRepositoryProtocol,
)
from app.domain.policies.message_posting import MessagePostingPolicy
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.domain.value_objects.message_send_key import MessageSendKey


class SendGroupMessageHandler:
    def __init__(
        self,
        groups: GroupMessageRepositoryProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
        attachments: AttachmentVerifierProtocol,
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._groups = groups
        self._clock = clock
        self._ids = ids
        self._attachments = attachments
        self._max_attempts = max_attempts

    async def __call__(
        self, command: SendGroupMessageCommand
    ) -> SendGroupMessageResult:
        client_id = ClientMessageId.from_uuid(command.client_message_id)
        content = MessageContent.from_parts(
            text=command.text, attachments=command.attachment_ids
        )
        send_key = MessageSendKey(
            sender_id=command.actor_id, client_message_id=client_id
        )
        message_id = self._ids()
        command_id = self._ids()
        for _ in range(self._max_attempts):
            snapshot = await self._groups.get_by_id(command.dialog_id)
            if snapshot is None:
                raise DialogNotFoundError(command.dialog_id)
            snapshot.dialog.require_can_send(command.actor_id)
            try:
                existing = await self._groups.get_sent_message(
                    command.dialog_id, send_key, at_revision=snapshot.revision
                )
            except GroupReadConflictError:
                continue
            if existing is not None:
                if (
                    existing.dialog_id != command.dialog_id
                    or existing.send_key != send_key
                    or existing.content.attachments != content.attachments
                    or (not existing.is_edited and existing.content != content)
                ):
                    raise MessageSendConflictError()
                # Даже replay должен условно подтвердить текущие права.
                if await self._groups.try_commit(snapshot, None, command_id=command_id):
                    return SendGroupMessageResult(
                        message=MessageDTO.from_domain(existing),
                        group_version=snapshot.dialog.version,
                    )
                continue

            if content.attachments:
                await self._attachments.require_ready(
                    command.actor_id, content.attachments
                )
            message = MessagePostingPolicy.create_message(
                dialog=snapshot.dialog,
                sender_id=command.actor_id,
                client_message_id=client_id,
                content=content,
                position=MessagePosition(
                    dialog_id=command.dialog_id, value=snapshot.last_position + 1
                ),
                message_id=message_id,
                now=self._clock(),
            )
            if await self._groups.try_commit(snapshot, message, command_id=command_id):
                return SendGroupMessageResult(
                    message=MessageDTO.from_domain(message),
                    group_version=snapshot.dialog.version,
                )

        raise ConcurrentModificationError("Group message revision kept changing")
