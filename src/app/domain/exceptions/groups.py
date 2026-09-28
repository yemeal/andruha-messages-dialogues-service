from typing import ClassVar

from app.domain.exceptions.base import DomainError
from app.domain.exceptions.dialogues import NotDialogParticipantError
from app.domain.limits import MAX_GROUP_MEMBERS, MAX_GROUP_TITLE_LENGTH


class InvalidGroupTitleError(DomainError):
    """Название группы должно быть непустым и не превышать установленный лимит."""

    default_message: ClassVar[str] = (
        f"Group title must be non-empty and between 1 and {MAX_GROUP_TITLE_LENGTH} characters after trimming"
    )


class NotGroupMemberError(NotDialogParticipantError):
    """Пользователь не является участником группового диалога."""

    default_message: ClassVar[str] = "User is not a member of the group dialog"


class NotGroupOwnerError(DomainError):
    """Передавать владение группой может только текущий владелец."""

    default_message: ClassVar[str] = "User is not the group owner"


class GroupMemberAlreadyExistsError(DomainError):
    """Пользователь уже состоит в группе."""

    default_message: ClassVar[str] = "User is already a member of the group dialog"


class CannotRemoveOwnerError(DomainError):
    """Владелец группы не может быть удален из участников."""

    default_message: ClassVar[str] = "Group owner cannot be removed from members"


class EmptyGroupMembersError(DomainError):
    """Групповой диалог должен содержать как минимум владельца."""

    default_message: ClassVar[str] = "Group dialog must contain at least the owner"


class GroupMemberLimitExceededError(DomainError):
    """Группа не может превышать лимит участников, включая владельца."""

    default_message: ClassVar[str] = (
        f"Group cannot contain more than {MAX_GROUP_MEMBERS} members"
    )
