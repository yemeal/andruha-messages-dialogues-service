from typing import ClassVar

from app.domain.exceptions.base import DomainError


class SelfDialogNotAllowedError(DomainError):
    """Личный диалог требует двух разных участников."""

    default_message: ClassVar[str] = "A direct dialog requires two different users"


class NotDialogParticipantError(DomainError):
    """Действие доступно только участнику диалога."""

    default_message: ClassVar[str] = "User is not a dialog participant"
