from datetime import datetime
from typing import Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field

from app.domain.base import Entity
from app.domain.clock import ensure_utc
from app.domain.exceptions.dialogues import NotDialogParticipantError


class SavedDialog(Entity):
    """
    Неизменяемый диалог пользователя с самим собой («Избранное» / Saved Messages).
    """

    user_id: Annotated[
        UUID,
        Field(
            description="Идентификатор пользователя — единственного участника и владельца диалога.",
        ),
    ]

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        dialog_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        """
        Фабричный метод создания личного пространства сохранённых сообщений.
        """
        return cls(
            id=dialog_id if dialog_id is not None else uuid7(),
            user_id=user_id,
            created_at=ensure_utc(now),
        )

    def __contains__(self, user_id: UUID) -> bool:
        """
        Проверяет, принадлежит ли данный идентификатор пользователю-владельцу диалога.
        """
        return user_id == self.user_id

    def peer_of(self, user_id: UUID) -> UUID:
        """
        Возвращает собеседника диалога (для Saved Messages собеседником является сам пользователь).
        """
        if user_id != self.user_id:
            raise NotDialogParticipantError()
        return self.user_id
