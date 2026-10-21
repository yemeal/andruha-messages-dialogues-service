import re
from datetime import datetime
from typing import Literal, Self
from uuid import UUID, uuid7

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.domain.clock import utc_now

REJECTION_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)+$")


class BaseEventModel(BaseModel):
    """Базовый класс для всех моделей событий с поддержкой camelCase в wire-контрактах."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
    )


class AttachmentSnapshotDTO(BaseEventModel):
    """Снимок метаданных вложения в каноническом сообщении."""

    object_id: UUID
    media_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=26214400)
    sha256_base64: str = Field(
        min_length=44, max_length=44, pattern=r"^[A-Za-z0-9+/]{43}=$"
    )


class MessageSnapshotDTO(BaseEventModel):
    """Снимок канонического сообщения по контракту message.v1."""

    message_id: UUID
    dialog_id: UUID
    sender_id: UUID
    sent_at: datetime
    text: str | None = Field(default=None, max_length=4096)
    attachments: tuple[AttachmentSnapshotDTO, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def validate_message(self) -> Self:
        if self.sent_at.utcoffset() is None:
            raise ValueError("sent_at must be timezone-aware")
        if self.text is None and not self.attachments:
            raise ValueError("Message must contain text or at least one attachment")
        return self


class MessagePersistedPayload(BaseEventModel):
    """Полезная нагрузка события message.persisted.v1 (для отправителя)."""

    target_user_id: UUID
    client_message_id: UUID
    message: MessageSnapshotDTO


class MessageCreatedPayload(BaseEventModel):
    """Полезная нагрузка события message.created.v1 (для получателя)."""

    target_user_id: UUID
    message: MessageSnapshotDTO


class ReceiptWatermarkAdvancedPayload(BaseEventModel):
    """Полезная нагрузка события receipt.watermark_advanced.v1."""

    target_user_id: UUID
    dialog_id: UUID
    kind: Literal["DELIVERED", "READ"]
    through_message_id: UUID
    through_message_time: datetime
    status_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.through_message_time.utcoffset() is None:
            raise ValueError("through_message_time must be timezone-aware")
        return self


class MessageRejectedPayload(BaseEventModel):
    """Полезная нагрузка события message.rejected.v1 (при постоянном отказе)."""

    target_user_id: UUID
    client_message_id: UUID
    dialog_id: UUID
    code: str = Field(max_length=100)
    retryable: Literal[False] = False

    @field_validator("code")
    @classmethod
    def validate_rejection_code(cls, value: str) -> str:
        if not REJECTION_CODE_PATTERN.match(value):
            raise ValueError(f"Invalid rejection code pattern: {value}")
        return value


class EventEnvelope[PayloadT: BaseEventModel](BaseEventModel):
    """
    Унифицированный конверт интеграционных событий Andruha (event-envelope.v1).
    """

    event_id: UUID = Field(default_factory=uuid7)
    event_type: str = Field(min_length=1, max_length=200)
    schema_version: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(default_factory=utc_now)
    producer: str = Field(default="andruha-messages-dialogues-service")
    correlation_id: UUID = Field(default_factory=uuid7)
    causation_id: UUID | None = None
    payload: PayloadT

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return self
