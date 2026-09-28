from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Self
from uuid import UUID, uuid7

from pydantic import Field, model_validator

from app.domain.base import VersionedMutableEntity
from app.domain.clock import ensure_utc
from app.domain.exceptions.receipts import (
    CheckpointMessageMismatchError,
    NotIncomingMessageError,
    ReadCheckpointExceedsDeliveredError,
    ReceiptActorMismatchError,
    ReceiptDialogMismatchError,
)
from app.domain.protocols import ReceiptDialog
from app.domain.value_objects.message_checkpoint import MessageCheckpoint
from app.domain.value_objects.message_position import MessagePosition

if TYPE_CHECKING:
    from app.domain.aggregates.message import Message


class ReceiptWatermark(VersionedMutableEntity):
    """
    Подтверждённая граница доставки и прочтения входящих сообщений участника в диалоге.
    """

    dialog_id: Annotated[
        UUID,
        Field(
            description="Идентификатор диалога (UUID).",
        ),
    ]
    user_id: Annotated[
        UUID,
        Field(
            description="Идентификатор участника-получателя входящих сообщений (UUID).",
        ),
    ]
    delivered_through: Annotated[
        MessageCheckpoint | None,
        Field(
            default=None,
            description="Граница подтверждённой доставки входящих сообщений.",
        ),
    ]
    read_through: Annotated[
        MessageCheckpoint | None,
        Field(
            default=None,
            description="Граница подтверждённого прочтения входящих сообщений.",
        ),
    ]

    @model_validator(mode="after")
    def _validate_watermark_invariants(self) -> Self:
        """
        Гарантирует инвариант: прочтение не может опережать доставку (read <= delivered).
        """
        for checkpoint in (self.delivered_through, self.read_through):
            if checkpoint is not None and checkpoint.dialog_id != self.dialog_id:
                raise ReceiptDialogMismatchError()
        if self.read_through is not None and (
            self.delivered_through is None or self.read_through > self.delivered_through
        ):
            raise ReadCheckpointExceedsDeliveredError()
        return self

    @classmethod
    def create_empty(
        cls,
        *,
        dialog_id: UUID,
        user_id: UUID,
        watermark_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        """
        Создаёт начальное пустое состояние ватермарки.
        """
        instant = ensure_utc(now)
        return cls(
            id=watermark_id if watermark_id is not None else uuid7(),
            dialog_id=dialog_id,
            user_id=user_id,
            delivered_through=None,
            read_through=None,
            created_at=instant,
            updated_at=instant,
            version=1,
        )

    def is_delivered(self, target: MessagePosition | MessageCheckpoint) -> bool:
        """
        Проверяет, входит ли позиция сообщения или чекпоинт в подтверждённую границу доставки.
        """
        pos = self._position_in_dialog(target)
        if self.delivered_through is None:
            return False
        if (
            isinstance(target, MessageCheckpoint)
            and pos == self.delivered_through.position
            and target.message_id != self.delivered_through.message_id
        ):
            raise CheckpointMessageMismatchError()
        return pos <= self.delivered_through.position

    def is_read(self, target: MessagePosition | MessageCheckpoint) -> bool:
        """
        Проверяет, входит ли позиция сообщения или чекпоинт в подтверждённую границу прочтения.
        """
        pos = self._position_in_dialog(target)
        if self.read_through is None:
            return False
        if (
            isinstance(target, MessageCheckpoint)
            and pos == self.read_through.position
            and target.message_id != self.read_through.message_id
        ):
            raise CheckpointMessageMismatchError()
        return pos <= self.read_through.position

    def _position_in_dialog(
        self, target: MessagePosition | MessageCheckpoint
    ) -> MessagePosition:
        if isinstance(target, MessageCheckpoint):
            position = target.position
        elif isinstance(target, MessagePosition):
            position = target
        else:
            raise TypeError("Receipt target must be a scoped message position")
        if position.dialog_id != self.dialog_id:
            raise ReceiptDialogMismatchError()
        return position

    def advance_delivered(
        self,
        *,
        actor_id: UUID,
        dialog: ReceiptDialog,
        through: Message,
        now: datetime,
    ) -> bool:
        """
        Сдвигает границу ДОСТАВКИ входящих сообщений.

        Если чекпоинт уже доставлен — это запоздалый/повторный ACK,
        метод возвращает False (no-op), версия и updated_at не меняются.
        """
        checkpoint = self._checkpoint_for_ack(actor_id, dialog, through)
        if self.is_delivered(checkpoint):
            return False

        return self._apply_changes(
            now=now,
            delivered_through=checkpoint,
        )

    def advance_read(
        self,
        *,
        actor_id: UUID,
        dialog: ReceiptDialog,
        through: Message,
        now: datetime,
    ) -> bool:
        """
        Сдвигает границу ПРОЧТЕНИЯ входящих сообщений.
        Автоматически подтягивает границу доставки: delivered_through = max(delivered, read).

        Если чекпоинт уже прочитан — это повторный ACK,
        метод возвращает False (no-op), версия и updated_at не меняются.
        """
        checkpoint = self._checkpoint_for_ack(actor_id, dialog, through)
        if self.is_read(checkpoint):
            return False

        new_delivered = (
            self.delivered_through if self.is_delivered(checkpoint) else checkpoint
        )
        return self._apply_changes(
            now=now,
            read_through=checkpoint,
            delivered_through=new_delivered,
        )

    def _checkpoint_for_ack(
        self,
        actor_id: UUID,
        dialog: ReceiptDialog,
        through: Message,
    ) -> MessageCheckpoint:
        if actor_id != self.user_id:
            raise ReceiptActorMismatchError()
        if dialog.id != self.dialog_id or through.dialog_id != self.dialog_id:
            raise ReceiptDialogMismatchError()
        dialog.require_message_access(sender_id=through.sender_id, reader_id=actor_id)
        if not dialog.supports_receipts or through.is_sent_by(actor_id):
            raise NotIncomingMessageError()
        return MessageCheckpoint.create(
            position=through.position,
            message_id=through.id,
            timestamp=through.created_at,
        )
