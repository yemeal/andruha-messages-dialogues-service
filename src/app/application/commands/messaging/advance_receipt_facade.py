from uuid import UUID

from app.application.commands.base import BaseCommand
from app.application.commands.dialogues.advance_direct_receipt.command import (
    AdvanceDirectReceiptCommand,
)
from app.application.commands.dialogues.advance_direct_receipt.handler import (
    AdvanceDirectReceiptHandler,
)
from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
    ReceiptKind,
)
from app.application.commands.groups.advance_receipt.handler import (
    AdvanceGroupReceiptHandler,
)
from app.application.dto.base import BaseDTO
from app.application.dto.receipts import ReceiptWatermarkDTO
from app.application.exceptions.dialogues import (
    ReceiptsNotSupportedError,
    UnsupportedDialogKindError,
)
from app.application.exceptions.groups import DialogNotFoundError
from app.application.ports.persistence.repositories.dialog_lookup import (
    DialogKind,
    DialogLookupProtocol,
)


class AdvanceReceiptFacadeResult(BaseDTO):
    watermark: ReceiptWatermarkDTO
    changed: bool
    dialog_kind: DialogKind


class AdvanceReceiptFacadeCommand(BaseCommand[AdvanceReceiptFacadeResult]):
    """Единая команда продвижения границ доставки/прочтения с маршрутизацией по dialog_id."""

    dialog_id: UUID
    actor_id: UUID
    kind: ReceiptKind
    through_message_id: UUID


class AdvanceReceiptFacadeHandler:
    def __init__(
        self,
        dialog_lookup: DialogLookupProtocol,
        advance_direct: AdvanceDirectReceiptHandler,
        advance_group: AdvanceGroupReceiptHandler,
    ) -> None:
        self._dialog_lookup = dialog_lookup
        self._advance_direct = advance_direct
        self._advance_group = advance_group

    async def __call__(
        self, command: AdvanceReceiptFacadeCommand
    ) -> AdvanceReceiptFacadeResult:
        kind = await self._dialog_lookup.get_dialog_kind(command.dialog_id)
        if kind is None:
            raise DialogNotFoundError(command.dialog_id)

        if kind is DialogKind.SAVED:
            raise ReceiptsNotSupportedError(command.dialog_id)

        if kind is DialogKind.DIRECT:
            result = await self._advance_direct(
                AdvanceDirectReceiptCommand(
                    dialog_id=command.dialog_id,
                    actor_id=command.actor_id,
                    kind=command.kind,
                    through_message_id=command.through_message_id,
                )
            )
            return AdvanceReceiptFacadeResult(
                watermark=result.watermark,
                changed=result.changed,
                dialog_kind=kind,
            )

        if kind is DialogKind.GROUP:
            result = await self._advance_group(
                AdvanceGroupReceiptCommand(
                    dialog_id=command.dialog_id,
                    actor_id=command.actor_id,
                    kind=command.kind,
                    through_message_id=command.through_message_id,
                )
            )
            return AdvanceReceiptFacadeResult(
                watermark=result.watermark,
                changed=result.changed,
                dialog_kind=kind,
            )

        raise UnsupportedDialogKindError(str(kind))
