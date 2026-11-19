from app.application.dto.base import BaseDTO
from app.application.dto.groups import GroupDialogDTO


class CreateGroupDialogResult(BaseDTO):
    dialog: GroupDialogDTO
