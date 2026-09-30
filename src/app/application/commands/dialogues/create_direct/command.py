from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.commands.dialogues.create_direct.result import (
    CreateDirectDialogResult,
)


class CreateDirectDialogCommand(BaseCommand[CreateDirectDialogResult]):
    actor_id: UUID
    peer_id: UUID
