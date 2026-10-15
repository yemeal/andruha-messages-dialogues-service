from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.dto.groups import GroupDialogDTO


class TransferGroupOwnershipCommand(BaseCommand[GroupDialogDTO]):
    dialog_id: UUID
    actor_id: UUID
    new_owner_id: UUID
    command_id: UUID
