from collections.abc import Callable
from datetime import datetime

from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.commands.groups.transfer_ownership.command import (
    TransferGroupOwnershipCommand,
)
from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.groups import (
    CannotTransferOwnershipToSelfError,
    ConcurrentModificationError,
    DialogNotFoundError,
    GroupOwnershipConflictError,
    GroupReadConflictError,
    InvalidGroupCasRetryAttemptsError,
)
from app.application.ports.persistence.models import GroupOwnershipIntent
from app.application.ports.persistence.repositories.group_commands import (
    GroupOwnershipRepositoryProtocol,
)


class TransferGroupOwnershipHandler:
    def __init__(
        self,
        groups: GroupOwnershipRepositoryProtocol,
        clock: Callable[[], datetime],
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise InvalidGroupCasRetryAttemptsError(max_attempts)
        self._groups = groups
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(self, command: TransferGroupOwnershipCommand) -> GroupDialogDTO:
        if command.new_owner_id == command.actor_id:
            raise CannotTransferOwnershipToSelfError()

        intent = GroupOwnershipIntent(
            dialog_id=command.dialog_id,
            actor_id=command.actor_id,
            new_owner_id=command.new_owner_id,
        )

        for _ in range(self._max_attempts):
            snapshot = await self._groups.get_by_id(command.dialog_id)
            if snapshot is None:
                raise DialogNotFoundError(command.dialog_id)

            try:
                accepted = await self._groups.get_ownership_result(
                    command.dialog_id, command.command_id, at_revision=snapshot.revision
                )
            except GroupReadConflictError:
                continue

            if accepted is not None:
                if accepted.intent != intent:
                    raise GroupOwnershipConflictError()
                return accepted.result

            group = snapshot.dialog.model_copy(deep=True)
            group.change_owner(
                command.new_owner_id, now=self._clock(), actor_id=command.actor_id
            )

            if await self._groups.try_commit_ownership(
                snapshot, group, command_id=command.command_id, intent=intent
            ):
                return GroupDialogDTO.from_domain(group)

        raise ConcurrentModificationError("Group ownership revision kept changing")
