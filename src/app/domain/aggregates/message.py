from datetime import datetime
from typing import Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field, model_validator

from app.domain.base import VersionedMutableEntity
from app.domain.clock import ensure_utc
from app.domain.exceptions.messages import (
    InvalidMessageEditMetadataError,
    NotMessageAuthorError,
    PositionDialogMismatchError,
)
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.domain.value_objects.message_send_key import MessageSendKey
from app.domain.value_objects.message_text import MessageText


class Message(VersionedMutableEntity):
    """Сообщение с редактируемым текстом и неизменной идентичностью отправки."""

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

    @model_validator(mode="after")
    def _validate_edit_metadata(self) -> Self:
        if self.version == 1 and self.updated_at is not None:
            raise InvalidMessageEditMetadataError()
        if self.version > 1 and self.updated_at is None:
            raise InvalidMessageEditMetadataError()
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
            updated_at=None,
            version=1,
        )

    def is_sent_by(self, user_id: UUID) -> bool:
        return self.sender_id == user_id

    def edit_text(
        self,
        *,
        actor_id: UUID,
        text: str | MessageText | None,
        now: datetime,
    ) -> bool:
        """Меняет только текст; совпадающий после нормализации текст — no-op."""
        if not self.is_sent_by(actor_id):
            raise NotMessageAuthorError()
        content = MessageContent.from_parts(
            text=text, attachments=self.content.attachments
        )
        return self._apply_changes(now=now, content=content)

    @property
    def send_key(self) -> MessageSendKey:
        return MessageSendKey(
            sender_id=self.sender_id, client_message_id=self.client_message_id
        )

    @property
    def text_value(self) -> str | None:
        return self.content.text_value

    @property
    def is_edited(self) -> bool:
        """Текст менялся хотя бы один раз; повтор того же текста не считается."""
        return self.updated_at is not None

    @property
    def edited_at(self) -> datetime | None:
        """Время последнего реального редактирования текста."""
        return self.updated_at
