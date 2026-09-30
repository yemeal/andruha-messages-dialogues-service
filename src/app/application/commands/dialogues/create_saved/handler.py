from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.dialogues.create_saved.command import (
    CreateSavedDialogCommand,
)
from app.application.commands.dialogues.create_saved.result import (
    CreateSavedDialogResult,
)
from app.application.commands.dialogues.projections import ensure_dialog_projections
from app.application.dto.dialogues import SavedDialogDTO
from app.application.ports.identity.registered_users import RegisteredUsersProtocol
from app.application.ports.persistence.models import CanonicalDialog
from app.application.ports.persistence.repositories.saved_dialogues import (
    SavedDialogRepositoryProtocol,
)
from app.application.ports.projections.dialogues import DialogProjectionsProtocol
from app.domain.aggregates.saved_dialog import SavedDialog


class CreateSavedDialogHandler:
    def __init__(
        self,
        saved_dialogs: SavedDialogRepositoryProtocol,
        projections: DialogProjectionsProtocol,
        registered_users: RegisteredUsersProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
    ) -> None:
        self._saved_dialogs = saved_dialogs
        self._projections = projections
        self._registered_users = registered_users
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, command: CreateSavedDialogCommand
    ) -> CreateSavedDialogResult:
        existing = await self._saved_dialogs.get_by_owner(command.actor_id)
        if existing is not None:
            canonical = CanonicalDialog(dialog=existing, created=False)
        else:
            await self._registered_users.require_registered(command.actor_id)
            candidate = SavedDialog.create(
                user_id=command.actor_id, dialog_id=self._ids(), now=self._clock()
            )
            canonical = await self._saved_dialogs.create_or_get(candidate)

        await ensure_dialog_projections(
            self._projections, canonical.dialog, (command.actor_id,)
        )
        return CreateSavedDialogResult(
            dialog=SavedDialogDTO.from_domain(canonical.dialog),
            created=canonical.created,
        )
