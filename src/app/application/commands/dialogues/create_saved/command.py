from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.commands.dialogues.create_saved.result import (
    CreateSavedDialogResult,
)


class CreateSavedDialogCommand(BaseCommand[CreateSavedDialogResult]):
    actor_id: UUID
