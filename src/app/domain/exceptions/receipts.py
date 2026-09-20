from typing import ClassVar

from app.domain.exceptions.base import DomainError


class ReadCheckpointExceedsDeliveredError(DomainError):
    """Граница прочтения не может опережать границу доставки."""

    default_message: ClassVar[str] = (
        "Read checkpoint cannot exceed delivered checkpoint"
    )
