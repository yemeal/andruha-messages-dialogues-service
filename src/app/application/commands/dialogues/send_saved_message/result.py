from app.application.dto.base import BaseDTO
from app.application.dto.messages import MessageDTO


class SendSavedMessageResult(BaseDTO):
    message: MessageDTO
