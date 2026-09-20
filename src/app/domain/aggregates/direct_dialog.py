from datetime import datetime
from typing import Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field

from app.domain.base import Entity
from app.domain.clock import utc_now
from app.domain.value_objects.direct_participants import DirectParticipants


class DirectDialog(Entity):
    """
    Неизменяемый личный диалог двух участников.
    """

    participants: Annotated[
        DirectParticipants,
        Field(
            description="Каноническая пара участников, независимая от инициатора диалога."
        ),
    ]

    @classmethod
    def create(
        cls,
        *,
        participants: DirectParticipants,
        dialog_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        """
        Создаёт кандидата; уникальность пары обеспечивает репозиторий.
        """
        return cls(
            id=dialog_id if dialog_id is not None else uuid7(),
            participants=participants,
            created_at=now if now is not None else utc_now(),
        )

    def __contains__(self, user_id: UUID) -> bool:
        """
        Проверяет участие пользователя в диалоге через оператор `in`.
        """
        return user_id in self.participants

    @property
    def as_tuple(self) -> tuple[UUID, UUID]:
        """
        Возвращает каноническую пару участников диалога в виде кортежа.
        """
        return self.participants.as_tuple

    @property
    def as_set(self) -> frozenset[UUID]:
        """
        Возвращает участников диалога в виде неизменяемого множества (frozenset).
        """
        return self.participants.as_set

    def peer_of(self, user_id: UUID) -> UUID:
        return self.participants.peer_of(user_id)
