from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
    ReceiptKind,
)
from app.application.commands.groups.advance_receipt.result import (
    AdvanceGroupReceiptResult,
)
from app.application.commands.groups.limits import MAX_GROUP_COMMAND_ATTEMPTS
from app.application.dto.receipts import ReceiptWatermarkDTO
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    DialogNotFoundError,
    GroupReadConflictError,
    MessageNotFoundError,
)
from app.application.ports.persistence.repositories.group_commands import (
    GroupReceiptRepositoryProtocol,
)
from app.domain.aggregates.receipt_watermark import ReceiptWatermark


class AdvanceGroupReceiptHandler:
    def __init__(
        self,
        groups: GroupReceiptRepositoryProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
        *,
        max_attempts: int = MAX_GROUP_COMMAND_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._groups = groups
        self._clock = clock
        self._ids = ids
        self._max_attempts = max_attempts

    async def __call__(
        self, command: AdvanceGroupReceiptCommand
    ) -> AdvanceGroupReceiptResult:
        watermark_id = self._ids()
        command_id = self._ids()
        for _ in range(self._max_attempts):
            snapshot = await self._groups.get_by_id(command.dialog_id)
            if snapshot is None:
                raise DialogNotFoundError(command.dialog_id)
            snapshot.dialog.require_can_read(command.actor_id)
            try:
                through = await self._groups.get_message(
                    command.dialog_id,
                    command.through_message_id,
                    at_revision=snapshot.revision,
                )
                watermark = await self._groups.get_receipt(
                    command.dialog_id,
                    command.actor_id,
                    at_revision=snapshot.revision,
                )
            except GroupReadConflictError:
                continue
            if through is None:
                raise MessageNotFoundError(command.through_message_id)
            if watermark is None:
                watermark = ReceiptWatermark.create_empty(
                    dialog_id=command.dialog_id,
                    user_id=command.actor_id,
                    watermark_id=watermark_id,
                    now=self._clock(),
                )
            else:
                watermark = watermark.model_copy(deep=True)
            if command.kind is ReceiptKind.READ:
                changed = watermark.advance_read(
                    actor_id=command.actor_id,
                    dialog=snapshot.dialog,
                    through=through,
                    now=self._clock(),
                )
            else:
                changed = watermark.advance_delivered(
                    actor_id=command.actor_id,
                    dialog=snapshot.dialog,
                    through=through,
                    now=self._clock(),
                )
            # No-op также проходит CAS, чтобы устаревший состав не дал успех.
            if await self._groups.try_commit(
                snapshot, watermark if changed else None, command_id=command_id
            ):
                return AdvanceGroupReceiptResult(
                    watermark=ReceiptWatermarkDTO.from_domain(watermark),
                    group_version=snapshot.dialog.version,
                    changed=changed,
                )

        raise ConcurrentModificationError("Group receipt revision kept changing")
