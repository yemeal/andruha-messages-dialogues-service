import unicodedata
from typing import Annotated, Any, Self

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.exceptions.groups import InvalidGroupTitleError


class GroupTitle(DomainModel):
    """
    Нормализованное и проверенное название группового диалога.
    """

    value: Annotated[
        str,
        Field(
            description="Название группового диалога (1-128 code points).",
        ),
    ]

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_and_validate(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise InvalidGroupTitleError()

        normalized = unicodedata.normalize("NFC", value).strip()

        if not normalized or len(normalized) > 128:
            raise InvalidGroupTitleError()

        return normalized

    @classmethod
    def from_str(cls, value: str) -> Self:
        """
        Фабрика создания названия группы из строки.
        """
        return cls(value=value)

    def __str__(self) -> str:
        return self.value

    def __len__(self) -> int:
        return len(self.value)

    def __repr__(self) -> str:
        return f"GroupTitle('{self.value}')"

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupTitle):
            return self.value == other.value
        return False
