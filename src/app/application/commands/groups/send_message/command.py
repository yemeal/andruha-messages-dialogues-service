from uuid import UUID

from pydantic import Field

from app.application.commands.base import BaseCommand
from app.application.commands.groups.send_message.result import SendGroupMessageResult


class SendGroupMessageCommand(BaseCommand[SendGroupMessageResult]):
    dialog_id: UUID
    actor_id: UUID
    client_message_id: UUID
    text: str | None = Field(default=None)
    attachment_ids: tuple[UUID, ...] = Field(default=())
