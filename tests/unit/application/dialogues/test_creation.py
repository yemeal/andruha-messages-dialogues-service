from uuid import UUID

import pytest

from app.application.commands.dialogues.create_direct.command import (
    CreateDirectDialogCommand,
)
from app.application.commands.dialogues.create_direct.handler import (
    CreateDirectDialogHandler,
)
from app.application.dto.dialogues import DirectDialogDTO


@pytest.mark.asyncio
async def test_reversed_pair_returns_one_dialog_visible_to_both_users(
    alice_id: UUID,
    bob_id: UUID,
    direct_dialogs,
    projections,
    registered_users,
    clock,
    ids,
) -> None:
    handler = CreateDirectDialogHandler(
        direct_dialogs=direct_dialogs,
        projections=projections,
        registered_users=registered_users,
        clock=clock.now,
        ids=ids.new_id,
    )

    first = await handler(CreateDirectDialogCommand(actor_id=alice_id, peer_id=bob_id))
    second = await handler(CreateDirectDialogCommand(actor_id=bob_id, peer_id=alice_id))

    assert first.created is True
    assert second.created is False
    assert first.dialog == second.dialog
    assert first.dialog.id.version == 7
    assert first.dialog.created_at == clock.now()
    assert tuple(
        DirectDialogDTO.from_domain(dialog) for dialog in projections.for_user(alice_id)
    ) == (first.dialog,)
    assert tuple(
        DirectDialogDTO.from_domain(dialog) for dialog in projections.for_user(bob_id)
    ) == (first.dialog,)
