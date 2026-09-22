import unicodedata
from typing import Annotated, Any, Self

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.exceptions.messages import InvalidMessageTextError


class MessageText(DomainModel):
    """
    Нормализованный и проверенный текст сообщения.
    """

    value: Annotated[
        str,
        Field(
            description="Нормализованный текст сообщения (1-4096 code points).",
        ),
    ]

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_and_validate(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise InvalidMessageTextError()

        # Unicode NFC
        normalized = unicodedata.normalize("NFC", value)
        # Newlines
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        # Удаление пробелов и переводов строк на краях сообщения
        normalized = normalized.strip()

        # Запрет пустых сообщений (включая состоящие только из пробелов)
        if not normalized:
            raise InvalidMessageTextError()

        if len(normalized) > 4096:
            raise InvalidMessageTextError()

        return normalized

    @classmethod
    def from_str(cls, value: str) -> Self:
        """
        Фабрика создания объекта текста сообщения из строки.
        """
        return cls(value=value)

    def __str__(self) -> str:
        return self.value

    def __len__(self) -> int:
        return len(self.value)

    def __repr__(self) -> str:
        return f"MessageText('{self.value}')"

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MessageText):
            return self.value == other.value
        return False
