from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.dialogues.projections import ensure_dialog_projections
from app.application.commands.groups.create_group.command import (
    CreateGroupDialogCommand,
)
from app.application.commands.groups.create_group.result import CreateGroupDialogResult
from app.application.dto.groups import GroupDialogDTO
from app.application.ports.identity.registered_users import RegisteredUsersProtocol
from app.application.ports.objects.attachments import AttachmentVerifierProtocol
from app.application.ports.persistence.repositories.group_commands import (
    GroupCreationRepositoryProtocol,
)
from app.application.ports.projections.dialogues import DialogProjectionsProtocol
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.exceptions.groups import GroupMemberLimitExceededError
from app.domain.limits import MAX_GROUP_MEMBERS
from app.domain.value_objects.group_title import GroupTitle
from app.domain.value_objects.object_id import ObjectId


class CreateGroupDialogHandler:
    def __init__(
        self,
        groups: GroupCreationRepositoryProtocol,
        projections: DialogProjectionsProtocol,
        registered_users: RegisteredUsersProtocol,
        attachments: AttachmentVerifierProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
    ) -> None:
        self._groups = groups
        self._projections = projections
        self._registered_users = registered_users
        self._attachments = attachments
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, command: CreateGroupDialogCommand
    ) -> CreateGroupDialogResult:
        # 1. Валидация заголовка до внешних вызовов
        title = GroupTitle.from_str(command.title)

        # 2. Проверка лимита участников в домене до сетевых обращений
        unique_members = {command.actor_id, *command.initial_member_ids}
        if len(unique_members) > MAX_GROUP_MEMBERS:
            raise GroupMemberLimitExceededError()

        # 3. Детерминированный порядок участников (создатель, затем остальные без дубликатов)
        ordered_members: list[UUID] = [command.actor_id]
        for member_id in command.initial_member_ids:
            if member_id != command.actor_id and member_id not in ordered_members:
                ordered_members.append(member_id)

        # 4. Проверка регистрации каждого участника в Identity через require_registered
        for user_id in ordered_members:
            await self._registered_users.require_registered(user_id)

        # 5. Проверка аватара при наличии
        if command.avatar_object_id is not None:
            await self._attachments.require_ready(
                command.actor_id, (ObjectId.from_uuid(command.avatar_object_id),)
            )

        # 6. Создание агрегата
        group = GroupDialog.create(
            title=title,
            owner_id=command.actor_id,
            dialog_id=self._ids(),
            initial_members=command.initial_member_ids,
            avatar_object_id=command.avatar_object_id,
            now=self._clock(),
        )

        # 7. Сохранение группы
        await self._groups.create_group(group)

        # 8. Обеспечение проекций: создатель строго первым, затем остальные участники
        projection_users = (
            command.actor_id,
            *(uid for uid in sorted(group.members) if uid != command.actor_id),
        )
        await ensure_dialog_projections(self._projections, group, projection_users)

        # 9. Результат
        return CreateGroupDialogResult(
            dialog=GroupDialogDTO.from_domain(group),
        )
