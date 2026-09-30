from uuid import UUID

import pytest

from app.application.commands.dialogues.create_saved.command import (
    CreateSavedDialogCommand,
)
from app.application.commands.dialogues.create_saved.handler import (
    CreateSavedDialogHandler,
)
from app.application.dto.dialogues import SavedDialogDTO


@pytest.mark.asyncio
async def test_repeated_creation_returns_one_saved_dialog_for_owner(
    saved_creation: CreateSavedDialogHandler, alice_id: UUID, projections, clock
) -> None:
    first = await saved_creation(CreateSavedDialogCommand(actor_id=alice_id))
    second = await saved_creation(CreateSavedDialogCommand(actor_id=alice_id))

    assert first.created is True
    assert second.created is False
    assert first.dialog == second.dialog
    assert first.dialog.user_id == alice_id
    assert first.dialog.created_at == clock.now()
    assert tuple(
        SavedDialogDTO.from_domain(dialog) for dialog in projections.for_user(alice_id)
    ) == (first.dialog,)
