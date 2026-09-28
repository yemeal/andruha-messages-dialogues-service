from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID, uuid7

from pydantic import Field, field_serializer, field_validator, model_validator

from app.domain.base import VersionedMutableEntity
from app.domain.clock import ensure_utc
from app.domain.exceptions.groups import (
    CannotRemoveOwnerError,
    EmptyGroupMembersError,
    GroupMemberAlreadyExistsError,
    GroupMemberLimitExceededError,
    NotGroupMemberError,
    NotGroupOwnerError,
)
from app.domain.limits import MAX_GROUP_MEMBERS
from app.domain.value_objects.group_title import GroupTitle
from app.domain.value_objects.object_id import ObjectId


class GroupDialog(VersionedMutableEntity):
    """
    Изменяемый агрегат группового диалога с поддержкой OCC-версионирования.
    """

    title: Annotated[
        GroupTitle,
        Field(
            description="Название группового диалога.",
        ),
    ]
    owner_id: Annotated[
        UUID,
        Field(
            description="Идентификатор создателя/владельца группы.",
        ),
    ]
    members: Annotated[
        frozenset[UUID],
        Field(
            description="Неизменяемое множество идентификаторов участников группы.",
        ),
    ]
    avatar_object_id: Annotated[
        ObjectId | None,
        Field(description="Ссылка на готовое изображение в Object Storage."),
    ] = Field(default=None)

    @field_serializer("avatar_object_id")
    def _serialize_avatar(self, value: ObjectId | None) -> UUID | None:
        return value.value if value is not None else None

    @field_validator("title", mode="before")
    @classmethod
    def _validate_title(cls, value: Any) -> GroupTitle:
        if isinstance(value, GroupTitle):
            return value
        if isinstance(value, str):
            return GroupTitle.from_str(value)
        return value

    @field_validator("members", mode="before")
    @classmethod
    def _validate_members(cls, value: Any) -> frozenset[UUID]:
        if isinstance(value, frozenset):
            return value
        if isinstance(value, (set, list, tuple)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if not self.members:
            raise EmptyGroupMembersError()
        if len(self.members) > MAX_GROUP_MEMBERS:
            raise GroupMemberLimitExceededError()
        if self.owner_id not in self.members:
            raise CannotRemoveOwnerError()
        return self

    @classmethod
    def create(
        cls,
        *,
        title: GroupTitle | str,
        owner_id: UUID,
        dialog_id: UUID | None = None,
        initial_members: Iterable[UUID] | None = None,
        avatar_object_id: ObjectId | UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        """
        Фабрика создания нового группового диалога.

        Создатель (owner_id) автоматически добавляется в список участников группы.
        """
        instant = ensure_utc(now)
        t = title if isinstance(title, GroupTitle) else GroupTitle.from_str(title)
        members: set[UUID] = {owner_id}
        if initial_members:
            members.update(initial_members)

        return cls(
            id=dialog_id if dialog_id is not None else uuid7(),
            title=t,
            owner_id=owner_id,
            members=frozenset(members),
            avatar_object_id=(
                ObjectId.model_validate(avatar_object_id)
                if avatar_object_id is not None
                else None
            ),
            created_at=instant,
            updated_at=instant,
            version=1,
        )

    def __contains__(self, user_id: UUID) -> bool:
        """
        Проверяет участие пользователя в группе через оператор in.
        """
        return user_id in self.members

    def require_can_send(self, user_id: UUID) -> None:
        """Публиковать сообщения может текущий участник группы."""
        self.require_can_read(user_id)

    def require_can_read(self, user_id: UUID) -> None:
        """Текущему участнику доступна вся история, в том числе до вступления."""
        if user_id not in self.members:
            raise NotGroupMemberError()

    @property
    def supports_receipts(self) -> bool:
        return True

    def require_message_access(self, *, sender_id: UUID, reader_id: UUID) -> None:
        # Автор мог покинуть группу; его сохранённые сообщения остаются историей.
        self.require_can_read(reader_id)

    @property
    def member_count(self) -> int:
        """
        Количество участников группы.
        """
        return len(self.members)

    def add_member(self, user_id: UUID, now: datetime, *, actor_id: UUID) -> bool:
        """
        Добавляет участника по действию текущего участника группы.
        """
        if actor_id not in self.members:
            raise NotGroupMemberError()
        if user_id in self.members:
            raise GroupMemberAlreadyExistsError()

        return self._apply_changes(now=now, members=self.members | {user_id})

    def remove_member(self, user_id: UUID, now: datetime, *, actor_id: UUID) -> bool:
        """
        Удаляет участника по действию другого участника. Владельца удалить нельзя.
        """
        if actor_id not in self.members:
            raise NotGroupMemberError()
        if user_id == self.owner_id:
            raise CannotRemoveOwnerError()
        if user_id not in self.members:
            raise NotGroupMemberError()

        return self._apply_changes(now=now, members=self.members - {user_id})

    def rename(
        self, new_title: GroupTitle | str, now: datetime, *, actor_id: UUID
    ) -> bool:
        """
        Переименовывает группу по действию участника; совпадающее название — no-op.
        """
        if actor_id not in self.members:
            raise NotGroupMemberError()
        t = GroupTitle.from_str(new_title) if isinstance(new_title, str) else new_title
        return self._apply_changes(now=now, title=t)

    def change_owner(
        self, new_owner_id: UUID, now: datetime, *, actor_id: UUID
    ) -> bool:
        """
        Текущий владелец передаёт владение другому существующему участнику.
        """
        if actor_id != self.owner_id:
            raise NotGroupOwnerError()
        if new_owner_id not in self.members:
            raise NotGroupMemberError()

        return self._apply_changes(now=now, owner_id=new_owner_id)

    def change_avatar(
        self, object_id: ObjectId | UUID, now: datetime, *, actor_id: UUID
    ) -> bool:
        """Меняет ссылку; готовность изображения и права на него проверяет application."""
        self.require_can_read(actor_id)
        reference = ObjectId.model_validate(object_id)
        return self._apply_changes(now=now, avatar_object_id=reference)

    def remove_avatar(self, now: datetime, *, actor_id: UUID) -> bool:
        """Снимает ссылку с группы, не удаляя внешний объект."""
        self.require_can_read(actor_id)
        return self._apply_changes(now=now, avatar_object_id=None)
