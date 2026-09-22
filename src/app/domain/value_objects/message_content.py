from typing import Annotated, Any, Self

from pydantic import Field, field_validator

from app.domain.base import DomainModel
from app.domain.value_objects.message_text import MessageText


class MessageContent(DomainModel):
    """
    Содержимое сообщения.

    В первом инкременте содержит валидированный текст сообщения.
    Спроектирован с возможностью расширения вложениями (attachments)
    без ломки существующего публичного контракта.
    """

    text: Annotated[
        MessageText,
        Field(
            description="Текстовое содержимое сообщения.",
        ),
    ]

    @field_validator("text", mode="before")
    @classmethod
    def _validate_text(cls, value: Any) -> MessageText:
        if isinstance(value, MessageText):
            return value
        if isinstance(value, str):
            return MessageText.from_str(value)
        return value

    @classmethod
    def from_text(cls, raw_text: str | MessageText) -> Self:
        """
        Фабрика создания содержимого сообщения из строки или готового MessageText.
        """
        if isinstance(raw_text, MessageText):
            return cls(text=raw_text)
        return cls(text=MessageText.from_str(raw_text))

    @property
    def text_value(self) -> str:
        """
        Возвращает нормализованную строку текста сообщения.
        """
        return self.text.value
