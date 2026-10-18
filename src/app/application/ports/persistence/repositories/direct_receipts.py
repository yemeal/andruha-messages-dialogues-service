from typing import Protocol
from uuid import UUID

from app.domain.aggregates.receipt_watermark import ReceiptWatermark


class DirectReceiptRepositoryProtocol(Protocol):
    """Долговременное хранение receipts/watermarks для 1:1 личных диалогов.

    Обеспечивает монотонность версий watermark и защиту от гонок через OCC (expected_version).
    """

    async def get_watermark(
        self, dialog_id: UUID, user_id: UUID
    ) -> ReceiptWatermark | None:
        """Получить текущую границу доставки/прочтения участника в личном диалоге."""
        ...

    async def save_watermark(
        self, watermark: ReceiptWatermark, *, expected_version: int
    ) -> bool:
        """Атомарно сохранить обновлённую границу с проверкой expected_version (OCC).

        Возвращает True в случае успеха, False при конфликте версий.
        """
        ...
