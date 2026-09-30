from app.application.dto.base import BaseDTO
from app.application.dto.dialogues import SavedDialogDTO


class CreateSavedDialogResult(BaseDTO):
    dialog: SavedDialogDTO
    created: bool
