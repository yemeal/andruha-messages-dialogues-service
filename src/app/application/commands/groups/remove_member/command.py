from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.dto.groups import GroupDialogDTO


class RemoveGroupMemberCommand(BaseCommand[GroupDialogDTO]):
    command_id: UUID
    dialog_id: UUID
    actor_id: UUID
    user_id: UUID
