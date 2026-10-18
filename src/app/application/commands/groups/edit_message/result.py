from app.application.dto.base import BaseDTO
from app.application.dto.messages import MessageDTO


class EditGroupMessageTextResult(BaseDTO):
    message: MessageDTO
    group_version: int
    changed: bool
