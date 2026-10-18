from app.application.dto.base import BaseDTO
from app.application.dto.receipts import ReceiptWatermarkDTO


class AdvanceDirectReceiptResult(BaseDTO):
    watermark: ReceiptWatermarkDTO
    changed: bool
