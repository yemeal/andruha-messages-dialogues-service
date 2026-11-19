from uuid import UUID

from pydantic import UUID7, Field

from app.application.commands.base import BaseCommand
from app.application.commands.groups.create_group.result import CreateGroupDialogResult


class CreateGroupDialogCommand(BaseCommand[CreateGroupDialogResult]):
    command_id: UUID7
    actor_id: UUID
    title: str
    initial_member_ids: tuple[UUID, ...] = Field(default=())
    avatar_object_id: UUID | None = Field(default=None)
