from datetime import datetime
from uuid import UUID

from app.domain.aggregates.message import Message
from app.domain.clock import ensure_utc
from app.domain.exceptions.messages import MessageCreatedAtPrecedesDialogError
from app.domain.protocols import PostingDialog
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition


class MessagePostingPolicy:
    """Проверяет правила загруженного диалога; сохранение выполняет application."""

    @staticmethod
    def create_message(
        *,
        dialog: PostingDialog,
        sender_id: UUID,
        client_message_id: ClientMessageId,
        content: MessageContent,
        position: MessagePosition,
        message_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Message:
        dialog.require_can_send(sender_id)
        instant = ensure_utc(now)
        if instant < dialog.created_at:
            raise MessageCreatedAtPrecedesDialogError()
        return Message.create(
            dialog_id=dialog.id,
            sender_id=sender_id,
            client_message_id=client_message_id,
            content=content,
            position=position,
            message_id=message_id,
            now=instant,
        )
