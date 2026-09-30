from typing import Protocol
from uuid import UUID

from app.application.ports.persistence.models import CanonicalDialog
from app.domain.aggregates.saved_dialog import SavedDialog


class SavedDialogRepositoryProtocol(Protocol):
    async def get_by_owner(self, user_id: UUID) -> SavedDialog | None: ...

    async def create_or_get(
        self, candidate: SavedDialog
    ) -> CanonicalDialog[SavedDialog]:
        """Атомарно возвращает единственный SavedDialog для владельца.

        При конкуренции и неизвестном исходе действуют гарантии DirectDialog.
        """
        ...
