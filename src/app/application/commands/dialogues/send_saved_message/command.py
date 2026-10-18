from uuid import UUID

from pydantic import Field

from app.application.commands.base import BaseCommand
from app.application.commands.dialogues.send_saved_message.result import (
    SendSavedMessageResult,
)


class SendSavedMessageCommand(BaseCommand[SendSavedMessageResult]):
    """Команда отправки сообщения в личное пространство «Избранное» (SavedDialog)."""

    dialog_id: UUID
    actor_id: UUID
    client_message_id: UUID = Field(
        description="UUIDv7 одной отправки; новый для нового сообщения, прежний для retry."
    )
    text: str | None = Field(default=None)
    attachment_ids: tuple[UUID, ...] = Field(default=())
