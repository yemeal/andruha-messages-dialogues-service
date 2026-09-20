from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.base import DomainModel
from app.domain.exceptions.dialogues import (
    NotDialogParticipantError,
    SelfDialogNotAllowedError,
)


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

    @model_validator(mode="after")
    def _canonicalize(self) -> Self:
        """
        Канонизирует два UUID по bytes.
        A-B и B-A равны и имеют одинаковый hash.
        """
        if self.first == self.second:
            raise SelfDialogNotAllowedError()
        if self.first.bytes > self.second.bytes:
            first, second = self.second, self.first
            object.__setattr__(self, "first", first)
            object.__setattr__(self, "second", second)
        return self
