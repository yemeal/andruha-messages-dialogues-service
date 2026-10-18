from app.application.dto.base import BaseDTO
from app.application.dto.messages import MessageDTO


class SendDirectMessageResult(BaseDTO):
    message: MessageDTO
