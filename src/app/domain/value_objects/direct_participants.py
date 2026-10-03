from collections.abc import Mapping
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from app.domain.base import DomainModel
from app.domain.exceptions.dialogues import (
    NotDialogParticipantError,
    SelfDialogNotAllowedError,
)

_USER_ID = TypeAdapter(UUID)


class DirectParticipants(DomainModel):
    """
    Каноническая пара участников, независимая от инициатора диалога.
    """

    first: Annotated[
        UUID,
        Field(
            description="Первый канонический идентификатор пользователя (UUID) пары.",
        ),
    ]
    second: Annotated[
        UUID,
        Field(
            description="Второй канонический идентификатор пользователя (UUID) пары.",
        ),
    ]

    @classmethod
    def from_user_ids(cls, first: UUID, second: UUID) -> Self:
        """
        Фабричный метод создания пары участников по их UUID.
        """
        return cls(first=first, second=second)

    def __contains__(self, user_id: UUID) -> bool:
        """
        Проверяет участие пользователя в диалоге через оператор `in`.
        """
        return user_id in (self.first, self.second)

    @property
    def as_tuple(self) -> tuple[UUID, UUID]:
        """
        Возвращает каноническую пару участников в виде кортежа.
        """
        return self.first, self.second

    @property
    def as_set(self) -> frozenset[UUID]:
        """
        Возвращает участников в виде неизменяемого множества (frozenset).
        """
        return frozenset((self.first, self.second))

    def peer_of(self, user_id: UUID) -> UUID:
        """
        Возвращает собеседника либо поднимает `NotDialogParticipantError`.
        """
        if user_id == self.first:
            return self.second
        if user_id == self.second:
            return self.first
        raise NotDialogParticipantError()

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_input(cls, value: object) -> object:
        """Нормализует отдельные входные данные до создания frozen-состояния."""
        if isinstance(value, Mapping):
            values = dict(value)
        else:
            values = {
                "first": getattr(value, "first", None),
                "second": getattr(value, "second", None),
            }
        try:
            first = _USER_ID.validate_python(values.get("first"))
            second = _USER_ID.validate_python(values.get("second"))
        except ValidationError:
            # Ошибки поля и missing/extra остаются в обычной валидации модели.
            return value
        if first.bytes > second.bytes:
            first, second = second, first
        return {**values, "first": first, "second": second}

    @model_validator(mode="after")
    def _validate_distinct_users(self) -> Self:
        if self.first == self.second:
            raise SelfDialogNotAllowedError()
        return self
