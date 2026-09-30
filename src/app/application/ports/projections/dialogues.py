from typing import Protocol
from uuid import UUID

from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog


class DialogProjectionsProtocol(Protocol):
    async def ensure_for_user(
        self, user_id: UUID, dialog: DirectDialog | SavedDialog
    ) -> None:
        """Подтверждает карточку и список канонического диалога для user_id.

        Повтор безопасен после частичной записи и использует ID/created_at
        победителя. Начальные activity/preview/unread не заменяют более новые
        значения. Ожидаемый отказ выражается ProjectionUnavailableError.
        """
        ...
