from datetime import datetime
from typing import Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field, model_validator

from app.domain.base import Entity
from app.domain.clock import ensure_utc
from app.domain.exceptions.messages import PositionDialogMismatchError
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.domain.value_objects.message_send_key import MessageSendKey


class Message(Entity):
    """Неизменяемое сообщение; правила диалога проверяются перед принятием."""

    dialog_id: Annotated[
        UUID, Field(description="Диалог, которому принадлежит сообщение.")
    ]
    sender_id: Annotated[UUID, Field(description="Автор сообщения.")]
    client_message_id: Annotated[
        ClientMessageId,
        Field(description="Клиентский идентификатор логической отправки."),
    ]
    content: Annotated[MessageContent, Field(description="Текст и ссылки на вложения.")]
    position: Annotated[
        MessagePosition, Field(description="Позиция в порядке истории диалога.")
    ]

    @model_validator(mode="after")
    def _validate_position_dialog(self) -> Self:
        if self.position.dialog_id != self.dialog_id:
            raise PositionDialogMismatchError()
        return self

    @classmethod
    def create(
        cls,
        *,
        dialog_id: UUID,
        sender_id: UUID,
        client_message_id: ClientMessageId,
        content: MessageContent,
        position: MessagePosition,
        message_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        """Создаёт кандидата, не подтверждая права автора или durable сохранение."""
        return cls(
            id=message_id if message_id is not None else uuid7(),
            dialog_id=dialog_id,
            sender_id=sender_id,
            client_message_id=client_message_id,
            content=content,
            position=position,
            created_at=ensure_utc(now),
        )

    def is_sent_by(self, user_id: UUID) -> bool:
        return self.sender_id == user_id

    @property
    def send_key(self) -> MessageSendKey:
        return MessageSendKey(
            sender_id=self.sender_id, client_message_id=self.client_message_id
        )

    @property
    def text_value(self) -> str | None:
        return self.content.text_value
