from uuid import UUID

from pydantic import Field

from app.application.commands.base import BaseCommand
from app.application.commands.groups.send_message.result import SendGroupMessageResult


class SendGroupMessageCommand(BaseCommand[SendGroupMessageResult]):
    """Новая отправка требует нового client ID; повтор сохраняет прежний ID.

    После реального редактирования текст повтора не определяет новое намерение:
    возвращается актуальное сообщение без дубля или перезаписи текста.
    """

    dialog_id: UUID
    actor_id: UUID
    client_message_id: UUID = Field(
        description="UUIDv7 одной отправки; новый для нового сообщения, прежний для retry."
    )
    text: str | None = Field(default=None)
    attachment_ids: tuple[UUID, ...] = Field(default=())
