from app.application.dto.base import BaseDTO
from app.application.dto.dialogues import DirectDialogDTO


class CreateDirectDialogResult(BaseDTO):
    dialog: DirectDialogDTO
    created: bool
