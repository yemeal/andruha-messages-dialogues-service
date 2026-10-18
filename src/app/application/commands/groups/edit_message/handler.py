from collections.abc import Callable
from datetime import datetime

from app.application.commands.groups.edit_message.command import (
    EditGroupMessageTextCommand,
)
from app.application.commands.groups.edit_message.result import (
    EditGroupMessageTextResult,
)
from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.dto.messages import MessageDTO
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    DialogNotFoundError,
    GroupReadConflictError,
    MessageNotFoundError,
)
from app.application.ports.persistence.repositories.group_commands import (
    GroupMessageRepositoryProtocol,
)


class EditGroupMessageTextHandler:
    def __init__(
        self,
        groups: GroupMessageRepositoryProtocol,
        clock: Callable[[], datetime],
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._groups = groups
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(
        self, command: EditGroupMessageTextCommand
    ) -> EditGroupMessageTextResult:
        for _ in range(self._max_attempts):
            snapshot = await self._groups.get_by_id(command.dialog_id)
            if snapshot is None:
                raise DialogNotFoundError(command.dialog_id)

            snapshot.dialog.require_can_read(command.actor_id)

            try:
                message = await self._groups.get_message_by_id(
                    command.dialog_id,
                    command.message_id,
                    at_revision=snapshot.revision,
                )
            except GroupReadConflictError:
                continue

            if message is None:
                raise MessageNotFoundError(command.message_id)

            candidate = message.model_copy(deep=True)
            changed = candidate.edit_text(
                actor_id=command.actor_id,
                text=command.new_text,
                now=self._clock(),
            )

            if await self._groups.try_commit(
                snapshot, candidate if changed else None, command_id=command.command_id
            ):
                return EditGroupMessageTextResult(
                    message=MessageDTO.from_domain(candidate),
                    group_version=snapshot.dialog.version,
                    changed=changed,
                )

        raise ConcurrentModificationError("Group message edit revision kept changing")
