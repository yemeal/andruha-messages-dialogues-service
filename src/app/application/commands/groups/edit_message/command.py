from uuid import UUID

from pydantic import Field

from app.application.commands.base import BaseCommand
from app.application.commands.groups.edit_message.result import (
    EditGroupMessageTextResult,
)


class EditGroupMessageTextCommand(BaseCommand[EditGroupMessageTextResult]):
    """Команда редактирования текста сообщения в групповом диалоге."""

    dialog_id: UUID
    actor_id: UUID
    message_id: UUID
    new_text: str | None = Field(default=None)
    command_id: UUID
