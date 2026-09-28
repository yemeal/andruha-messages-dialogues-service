from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.domain.base import DomainModel
from app.domain.value_objects.client_message_id import ClientMessageId


class MessageSendKey(DomainModel):
    """Идентичность одной логической отправки в пределах отправителя."""

    sender_id: Annotated[
        UUID,
        Field(description="Пользователь, инициировавший отправку."),
    ]
    client_message_id: Annotated[
        ClientMessageId,
        Field(description="Стабильный клиентский ID при повторах отправки."),
    ]
