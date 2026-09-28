from collections.abc import Iterable
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import Field, field_serializer, field_validator, model_validator

from app.domain.base import DomainModel
from app.domain.exceptions.messages import (
    EmptyMessageContentError,
    InvalidMessageAttachmentsError,
)
from app.domain.limits import MAX_MESSAGE_ATTACHMENTS
from app.domain.value_objects.message_text import MessageText
from app.domain.value_objects.object_id import ObjectId


class MessageContent(DomainModel):
    """
    Содержимое сообщения.

    Валидированный текст и идентификаторы вложений; хотя бы одна часть непустая.
    """

    text: Annotated[
        MessageText | None,
        Field(
            default=None,
            description="Текстовое содержимое сообщения, если оно есть.",
        ),
    ]
    attachments: Annotated[
        tuple[ObjectId, ...],
        Field(default=(), description="Идентификаторы объектов в порядке отправки."),
    ]

    @field_validator("text", mode="before")
    @classmethod
    def _validate_text(cls, value: Any) -> MessageText | None:
        if isinstance(value, MessageText):
            return value
        if isinstance(value, str):
            if not value.strip():
                return None
            return MessageText.from_str(value)
        return value

    @model_validator(mode="after")
    def _validate_nonempty(self) -> Self:
        if self.text is None and not self.attachments:
            raise EmptyMessageContentError()
        if len(self.attachments) > MAX_MESSAGE_ATTACHMENTS:
            raise InvalidMessageAttachmentsError()
        if len(self.attachments) != len(set(self.attachments)):
            raise InvalidMessageAttachmentsError()
        return self

    @field_serializer("attachments")
    def _serialize_attachments(self, values: tuple[ObjectId, ...]) -> tuple[UUID, ...]:
        return tuple(reference.value for reference in values)

    @classmethod
    def from_text(cls, raw_text: str | MessageText) -> Self:
        """
        Фабрика создания содержимого сообщения из строки или готового MessageText.
        """
        if isinstance(raw_text, MessageText):
            return cls(text=raw_text)
        return cls(text=MessageText.from_str(raw_text))

    @classmethod
    def from_parts(
        cls,
        *,
        text: str | MessageText | None = None,
        attachments: Iterable[ObjectId | UUID] = (),
    ) -> Self:
        """Создаёт текстовое, смешанное или содержащее только вложения сообщение."""
        return cls.model_validate({"text": text, "attachments": tuple(attachments)})

    @property
    def text_value(self) -> str | None:
        """
        Возвращает нормализованную строку текста сообщения.
        """
        return self.text.value if self.text is not None else None
