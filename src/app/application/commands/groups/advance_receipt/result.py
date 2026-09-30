from app.application.dto.base import BaseDTO
from app.application.dto.receipts import ReceiptWatermarkDTO


class AdvanceGroupReceiptResult(BaseDTO):
    watermark: ReceiptWatermarkDTO
    group_version: int
    changed: bool
