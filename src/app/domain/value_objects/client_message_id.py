from typing import Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.exceptions.messages import InvalidClientMessageIdVersionError


class ClientMessageId(DomainModel):
    """
    Клиентский токен идемпотентности отправки сообщения (строго UUIDv7).
    """

    value: Annotated[
        UUID,
        Field(
            description="Клиентский токен идемпотентности сообщения (UUIDv7).",
        ),
    ]

    @field_validator("value")
    @classmethod
    def _validate_version(cls, value: UUID) -> UUID:
        if value.version != 7:
            raise InvalidClientMessageIdVersionError()
        return value

    @classmethod
    def generate(cls) -> Self:
        """
        Генерирует новый клиентский идентификатор версии 7.
        """
        return cls(value=uuid7())

    @classmethod
    def from_uuid(cls, value: UUID) -> Self:
        """
        Создаёт объект-значение из существующего UUID.
        """
        return cls(value=value)

    @classmethod
    def from_str(cls, value: str) -> Self:
        """
        Парсит строковое представление UUID.
        """
        return cls(value=UUID(value))

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"ClientMessageId('{self.value}')"

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ClientMessageId):
            return self.value == other.value
        return False
