from collections.abc import Callable
from datetime import datetime

from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.commands.groups.rename.command import RenameGroupDialogCommand
from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    DialogNotFoundError,
    GroupMetadataConflictError,
    GroupReadConflictError,
    InvalidGroupCasRetryAttemptsError,
)
from app.application.ports.persistence.models import (
    GroupMetadataIntent,
    MetadataAction,
)
from app.application.ports.persistence.repositories.group_commands import (
    GroupMetadataRepositoryProtocol,
)
from app.domain.value_objects.group_title import GroupTitle


class RenameGroupDialogHandler:
    def __init__(
        self,
        groups: GroupMetadataRepositoryProtocol,
        clock: Callable[[], datetime],
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise InvalidGroupCasRetryAttemptsError(max_attempts)
        self._groups = groups
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(self, command: RenameGroupDialogCommand) -> GroupDialogDTO:
        # Валидация заголовка до сетевых/дисковых обращений
        title = GroupTitle.from_str(command.new_title)

        intent = GroupMetadataIntent(
            dialog_id=command.dialog_id,
            actor_id=command.actor_id,
            action=MetadataAction.RENAME,
            title=title,
        )
        for _ in range(self._max_attempts):
            snapshot = await self._groups.get_by_id(command.dialog_id)
            if snapshot is None:
                raise DialogNotFoundError(command.dialog_id)

            try:
                accepted = await self._groups.get_metadata_result(
                    command.dialog_id, command.command_id, at_revision=snapshot.revision
                )
            except GroupReadConflictError:
                continue

            if accepted is not None:
                if accepted.intent != intent:
                    raise GroupMetadataConflictError()
                return accepted.result

            group = snapshot.dialog.model_copy(deep=True)
            group.rename(title, now=self._clock(), actor_id=command.actor_id)

            if await self._groups.try_commit_metadata(
                snapshot, group, command_id=command.command_id, intent=intent
            ):
                return GroupDialogDTO.from_domain(group)

        raise ConcurrentModificationError("Group metadata revision kept changing")
