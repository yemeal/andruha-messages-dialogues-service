from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.dialogues.advance_direct_receipt.command import (
    AdvanceDirectReceiptCommand,
    ReceiptKind,
)
from app.application.commands.dialogues.advance_direct_receipt.result import (
    AdvanceDirectReceiptResult,
)
from app.application.dto.receipts import ReceiptWatermarkDTO
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    DialogNotFoundError,
    MessageNotFoundError,
)
from app.application.ports.persistence.repositories.direct_dialogues import (
    DirectDialogRepositoryProtocol,
)
from app.application.ports.persistence.repositories.direct_messages import (
    DirectMessageRepositoryProtocol,
)
from app.application.ports.persistence.repositories.direct_receipts import (
    DirectReceiptRepositoryProtocol,
)
from app.domain.aggregates.receipt_watermark import ReceiptWatermark


class AdvanceDirectReceiptHandler:
    def __init__(
        self,
        direct_dialogs: DirectDialogRepositoryProtocol,
        direct_messages: DirectMessageRepositoryProtocol,
        direct_receipts: DirectReceiptRepositoryProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
    ) -> None:
        self._direct_dialogs = direct_dialogs
        self._direct_messages = direct_messages
        self._direct_receipts = direct_receipts
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, command: AdvanceDirectReceiptCommand
    ) -> AdvanceDirectReceiptResult:
        dialog = await self._direct_dialogs.get_by_id(command.dialog_id)
        if dialog is None:
            raise DialogNotFoundError(command.dialog_id)
        dialog.require_can_read(command.actor_id)

        through = await self._direct_messages.get_message_by_id(
            command.dialog_id, command.through_message_id
        )
        if through is None:
            raise MessageNotFoundError(command.through_message_id)

        watermark = await self._direct_receipts.get_watermark(
            command.dialog_id, command.actor_id
        )
        if watermark is None:
            watermark = ReceiptWatermark.create_empty(
                dialog_id=command.dialog_id,
                user_id=command.actor_id,
                watermark_id=self._ids(),
                now=self._clock(),
            )
            expected_version = 0
        else:
            expected_version = watermark.version
            watermark = watermark.model_copy(deep=True)

        if command.kind is ReceiptKind.READ:
            changed = watermark.advance_read(
                actor_id=command.actor_id,
                dialog=dialog,
                through=through,
                now=self._clock(),
            )
        else:
            changed = watermark.advance_delivered(
                actor_id=command.actor_id,
                dialog=dialog,
                through=through,
                now=self._clock(),
            )

        if not changed:
            return AdvanceDirectReceiptResult(
                watermark=ReceiptWatermarkDTO.from_domain(watermark),
                changed=False,
            )

        success = await self._direct_receipts.save_watermark(
            watermark, expected_version=expected_version
        )
        if not success:
            raise ConcurrentModificationError("Direct receipt version conflict")

        return AdvanceDirectReceiptResult(
            watermark=ReceiptWatermarkDTO.from_domain(watermark),
            changed=True,
        )
