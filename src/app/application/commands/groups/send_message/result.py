from app.application.dto.base import BaseDTO
from app.application.dto.messages import MessageDTO


class SendGroupMessageResult(BaseDTO):
    message: MessageDTO
    group_version: int
