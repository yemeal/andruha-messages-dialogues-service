from typing import Protocol

from app.application.ports.persistence.models import CanonicalDialog
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.value_objects.direct_participants import DirectParticipants


class DirectDialogRepositoryProtocol(Protocol):
    async def get_by_participants(
        self, participants: DirectParticipants
    ) -> DirectDialog | None: ...

    async def create_or_get(
        self, candidate: DirectDialog
    ) -> CanonicalDialog[DirectDialog]:
        """Атомарно возвращает одного сохранённого победителя для A-B и B-A.

        ID/created_at проигравшего кандидата никогда не становятся результатом.
        Неизвестный исход разрешается по канонической записи; если он не
        установлен, поднимается StorageUnavailableError, а не новый успех.
        """
        ...
