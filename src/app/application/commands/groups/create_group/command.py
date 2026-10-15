from uuid import UUID

from pydantic import Field

from app.application.commands.base import BaseCommand
from app.application.commands.groups.create_group.result import CreateGroupDialogResult


class CreateGroupDialogCommand(BaseCommand[CreateGroupDialogResult]):
    actor_id: UUID
    title: str
    initial_member_ids: tuple[UUID, ...] = Field(default=())
    avatar_object_id: UUID | None = Field(default=None)
