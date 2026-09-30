from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.application.commands.dialogues.create_direct.command import (
    CreateDirectDialogCommand,
)
from app.application.commands.dialogues.create_direct.result import (
    CreateDirectDialogResult,
)
from app.application.commands.dialogues.projections import ensure_dialog_projections
from app.application.dto.dialogues import DirectDialogDTO
from app.application.ports.identity.registered_users import RegisteredUsersProtocol
from app.application.ports.persistence.models import CanonicalDialog
from app.application.ports.persistence.repositories.direct_dialogues import (
    DirectDialogRepositoryProtocol,
)
from app.application.ports.projections.dialogues import DialogProjectionsProtocol
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.value_objects.direct_participants import DirectParticipants


class CreateDirectDialogHandler:
    def __init__(
        self,
        direct_dialogs: DirectDialogRepositoryProtocol,
        projections: DialogProjectionsProtocol,
        registered_users: RegisteredUsersProtocol,
        clock: Callable[[], datetime],
        ids: Callable[[], UUID],
    ) -> None:
        self._direct_dialogs = direct_dialogs
        self._projections = projections
        self._registered_users = registered_users
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, command: CreateDirectDialogCommand
    ) -> CreateDirectDialogResult:
        participants = DirectParticipants.from_user_ids(
            command.actor_id, command.peer_id
        )
        existing = await self._direct_dialogs.get_by_participants(participants)
        if existing is not None:
            canonical = CanonicalDialog(dialog=existing, created=False)
        else:
            for user_id in participants.as_tuple:
                await self._registered_users.require_registered(user_id)
            candidate = DirectDialog.create(
                participants=participants, dialog_id=self._ids(), now=self._clock()
            )
            canonical = await self._direct_dialogs.create_or_get(candidate)

        await ensure_dialog_projections(
            self._projections, canonical.dialog, participants.as_tuple
        )
        return CreateDirectDialogResult(
            dialog=DirectDialogDTO.from_domain(canonical.dialog),
            created=canonical.created,
        )
