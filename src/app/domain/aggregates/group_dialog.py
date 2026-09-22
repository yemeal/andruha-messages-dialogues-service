from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID, uuid7

from pydantic import Field, field_validator, model_validator

from app.domain.base import VersionedMutableEntity
from app.domain.clock import ensure_utc
from app.domain.exceptions.groups import (
    CannotRemoveOwnerError,
    EmptyGroupMembersError,
    GroupMemberAlreadyExistsError,
    NotGroupMemberError,
)
from app.domain.value_objects.group_title import GroupTitle


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
            created_at=instant,
            updated_at=instant,
            version=1,
        )

    def __contains__(self, user_id: UUID) -> bool:
        """
        Проверяет участие пользователя в группе через оператор in.
        """
        return user_id in self.members

    @property
    def member_count(self) -> int:
        """
        Количество участников группы.
        """
        return len(self.members)

    def add_member(self, user_id: UUID, now: datetime) -> bool:
        """
        Добавляет нового участника в группу.
        """
        if user_id in self.members:
            raise GroupMemberAlreadyExistsError()

        return self._apply_changes(now=now, members=self.members | {user_id})

    def remove_member(self, user_id: UUID, now: datetime) -> bool:
        """
        Удаляет участника из группы. Владельца удалить нельзя.
        """
        if user_id == self.owner_id:
            raise CannotRemoveOwnerError()
        if user_id not in self.members:
            raise NotGroupMemberError()

        return self._apply_changes(now=now, members=self.members - {user_id})

    def rename(self, new_title: GroupTitle | str, now: datetime) -> bool:
        """
        Переименовывает группу. Если название совпадает с текущим — no-op.
        """
        t = GroupTitle.from_str(new_title) if isinstance(new_title, str) else new_title
        return self._apply_changes(now=now, title=t)

    def change_owner(self, new_owner_id: UUID, now: datetime) -> bool:
        """
        Передаёт владение группой другому существующему участнику.
        """
        if new_owner_id not in self.members:
            raise NotGroupMemberError()

        return self._apply_changes(now=now, owner_id=new_owner_id)
