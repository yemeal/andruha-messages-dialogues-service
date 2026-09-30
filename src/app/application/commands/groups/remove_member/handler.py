from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    DialogNotFoundError,
)
from app.application.ports.persistence.repositories.group_commands import (
    GroupCommandRepositoryProtocol,
)


class RemoveGroupMemberHandler:
    def __init__(
        self,
        groups: GroupCommandRepositoryProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._groups = groups
        self._clock = clock
        self._ids = ids
        self._max_attempts = max_attempts

    async def __call__(self, command: RemoveGroupMemberCommand) -> GroupDialogDTO:
        command_id = self._ids()
        for _ in range(self._max_attempts):
            snapshot = await self._groups.get_by_id(command.dialog_id)
            if snapshot is None:
                raise DialogNotFoundError(command.dialog_id)
            group = snapshot.dialog.model_copy(deep=True)
            group.remove_member(
                command.user_id, now=self._clock(), actor_id=command.actor_id
            )
            if await self._groups.try_commit(snapshot, group, command_id=command_id):
                return GroupDialogDTO.from_domain(group)

        raise ConcurrentModificationError("Group membership revision kept changing")
