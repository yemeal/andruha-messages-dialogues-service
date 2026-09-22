from typing import ClassVar

from app.domain.exceptions.base import DomainError


class InvalidGroupTitleError(DomainError):
    """Название группы должно содержать от 1 до 128 символов."""

    default_message: ClassVar[str] = (
        "Group title must be non-empty and between 1 and 128 characters after trimming"
    )


class NotGroupMemberError(DomainError):
    """Пользователь не является участником группового диалога."""

    default_message: ClassVar[str] = "User is not a member of the group dialog"


class GroupMemberAlreadyExistsError(DomainError):
    """Пользователь уже состоит в группе."""

    default_message: ClassVar[str] = "User is already a member of the group dialog"


class CannotRemoveOwnerError(DomainError):
    """Владелец группы не может быть удален из участников."""

    default_message: ClassVar[str] = "Group owner cannot be removed from members"


class EmptyGroupMembersError(DomainError):
    """Групповой диалог должен содержать как минимум владельца."""

    default_message: ClassVar[str] = "Group dialog must contain at least the owner"
