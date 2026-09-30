from uuid import UUID

import pytest

from app.application.commands.dialogues.create_direct.command import (
    CreateDirectDialogCommand,
)
from app.application.commands.dialogues.create_direct.handler import (
    CreateDirectDialogHandler,
)
from app.application.commands.dialogues.create_saved.command import (
    CreateSavedDialogCommand,
)
from app.application.commands.dialogues.create_saved.handler import (
    CreateSavedDialogHandler,
)
from app.application.dto.dialogues import DirectDialogDTO, SavedDialogDTO
from app.application.exceptions.dependencies import (
    IdentityUnavailableError,
    ProjectionUnavailableError,
)
from app.application.exceptions.dialogues import DialogProjectionsIncompleteError
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog


class InterruptedProjections:
    def __init__(self, failing_user: UUID) -> None:
        self.failing_user: UUID | None = failing_user
        self.rows: dict[UUID, DirectDialog | SavedDialog] = {}

    async def ensure_for_user(
        self, user_id: UUID, dialog: DirectDialog | SavedDialog
    ) -> None:
        if user_id == self.failing_user:
            raise ProjectionUnavailableError("Projection write is not confirmed")
        self.rows.setdefault(user_id, dialog)

    def for_user(self, user_id: UUID) -> DirectDialog | SavedDialog | None:
        return self.rows.get(user_id)


class UnavailableIdentity:
    async def require_registered(self, user_id: UUID) -> None:
        raise IdentityUnavailableError("Identity is unavailable during recovery")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["direct", "saved"])
async def test_retry_completes_projections_from_canonical_state_without_identity(
    alice_id: UUID,
    bob_id: UUID,
    direct_dialogs,
    saved_dialogs,
    registered_users,
    clock,
    ids,
    kind: str,
) -> None:
    projections = InterruptedProjections(bob_id if kind == "direct" else alice_id)
    with pytest.raises(DialogProjectionsIncompleteError) as error:
        if kind == "direct":
            handler = CreateDirectDialogHandler(
                direct_dialogs, projections, registered_users, clock.now, ids.new_id
            )
            await handler(CreateDirectDialogCommand(actor_id=alice_id, peer_id=bob_id))
        else:
            handler = CreateSavedDialogHandler(
                saved_dialogs, projections, registered_users, clock.now, ids.new_id
            )
            await handler(CreateSavedDialogCommand(actor_id=alice_id))

    assert isinstance(error.value.__cause__, ProjectionUnavailableError)
    persisted_id = error.value.dialog_id
    projections.failing_user = None
    if kind == "direct":
        recovering_handler = CreateDirectDialogHandler(
            direct_dialogs, projections, UnavailableIdentity(), clock.now, ids.new_id
        )
        result = await recovering_handler(
            CreateDirectDialogCommand(actor_id=bob_id, peer_id=alice_id)
        )
        assert (
            DirectDialogDTO.from_domain(projections.for_user(bob_id)) == result.dialog
        )
        assert (
            DirectDialogDTO.from_domain(projections.for_user(alice_id)) == result.dialog
        )
    else:
        recovering_handler = CreateSavedDialogHandler(
            saved_dialogs, projections, UnavailableIdentity(), clock.now, ids.new_id
        )
        result = await recovering_handler(CreateSavedDialogCommand(actor_id=alice_id))
        assert (
            SavedDialogDTO.from_domain(projections.for_user(alice_id)) == result.dialog
        )

    assert result.created is False
    assert result.dialog.id == persisted_id
    assert result.dialog.created_at == clock.now()
