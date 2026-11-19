from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.dto.groups import GroupDialogDTO


class RenameGroupDialogCommand(BaseCommand[GroupDialogDTO]):
    dialog_id: UUID
    actor_id: UUID
    command_id: UUID
    new_title: str
