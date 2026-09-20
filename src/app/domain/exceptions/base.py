from typing import ClassVar


class DomainError(Exception):
    """Ожидаемое нарушение правила предметной области."""

    default_message: ClassVar[str] = "Domain error"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class InvalidDomainTimestampError(DomainError):
    """Время домена требует явно заданного часового пояса."""

    default_message: ClassVar[str] = "Domain timestamp must be timezone-aware"
