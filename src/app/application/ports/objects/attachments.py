from typing import Protocol
from uuid import UUID

from app.domain.value_objects.object_id import ObjectId


class AttachmentVerifierProtocol(Protocol):
    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        """Подтверждает готовность и право sender_id прикрепить все объекты.

        Проверка опирается на контракт Object Storage, а не на факт наличия
        UUID. Отказ или недоступность зависимости не допускают принятия.
        """
        ...
