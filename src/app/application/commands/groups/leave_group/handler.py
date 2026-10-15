from collections.abc import Callable
from datetime import datetime

from app.application.commands.groups.leave_group.command import LeaveGroupCommand
from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.remove_member.handler import (
    RemoveGroupMemberHandler,
)
from app.application.dto.groups import GroupDialogDTO
from app.application.ports.persistence.repositories.group_commands import (
    GroupMembershipRepositoryProtocol,
)


class LeaveGroupHandler:
    def __init__(
        self,
        groups: GroupMembershipRepositoryProtocol,
        clock: Callable[[], datetime],
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        self._delegate = RemoveGroupMemberHandler(
            groups=groups, clock=clock, max_attempts=max_attempts
        )

    async def __call__(self, command: LeaveGroupCommand) -> GroupDialogDTO:
        return await self._delegate(
            RemoveGroupMemberCommand(
                dialog_id=command.dialog_id,
                actor_id=command.actor_id,
                user_id=command.actor_id,
                command_id=command.command_id,
            )
        )
