from datetime import datetime
from typing import Self
from uuid import UUID

from app.application.dto.base import BaseDTO
from app.domain.aggregates.message import Message


class MessageDTO(BaseDTO):
    id: UUID
    dialog_id: UUID
    sender_id: UUID
    client_message_id: UUID
    text: str | None
    attachment_ids: tuple[UUID, ...]
    position: int
    version: int
    created_at: datetime
    edited_at: datetime | None

    @classmethod
    def from_domain(cls, message: Message) -> Self:
        return cls(
            id=message.id,
            dialog_id=message.dialog_id,
            sender_id=message.sender_id,
            client_message_id=message.client_message_id.value,
            text=message.text_value,
            attachment_ids=tuple(item.value for item in message.content.attachments),
            position=message.position.value,
            version=message.version,
            created_at=message.created_at,
            edited_at=message.edited_at,
        )
