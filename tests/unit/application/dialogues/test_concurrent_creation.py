import asyncio
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
from app.application.ports.persistence.models import CanonicalDialog
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.direct_participants import DirectParticipants


class ConcurrentDirectDialogs:
    def __init__(self) -> None:
        self.barrier = asyncio.Barrier(2)
        self.dialog: DirectDialog | None = None

    async def get_by_participants(
        self, participants: DirectParticipants
    ) -> DirectDialog | None:
        snapshot = self.dialog
        await self.barrier.wait()
        return snapshot

    async def create_or_get(
        self, candidate: DirectDialog
    ) -> CanonicalDialog[DirectDialog]:
        if self.dialog is not None:
            return CanonicalDialog(self.dialog, False)
        self.dialog = candidate
        return CanonicalDialog(candidate, True)


class ConcurrentSavedDialogs:
    def __init__(self) -> None:
        self.barrier = asyncio.Barrier(2)
        self.dialog: SavedDialog | None = None

    async def get_by_owner(self, user_id: UUID) -> SavedDialog | None:
        snapshot = self.dialog
        await self.barrier.wait()
        return snapshot

    async def create_or_get(
        self, candidate: SavedDialog
    ) -> CanonicalDialog[SavedDialog]:
        if self.dialog is not None:
            return CanonicalDialog(self.dialog, False)
        self.dialog = candidate
        return CanonicalDialog(candidate, True)


@pytest.mark.asyncio
async def test_concurrent_reversed_creators_use_repository_winner_for_both_projections(
    alice_id: UUID, bob_id: UUID, registered_users, projections, clock, ids
) -> None:
    repository = ConcurrentDirectDialogs()
    first_handler = CreateDirectDialogHandler(
        repository, projections, registered_users, clock.now, ids.new_id
    )
    second_handler = CreateDirectDialogHandler(
        repository, projections, registered_users, clock.now, ids.new_id
    )
    first, second = await asyncio.wait_for(
        asyncio.gather(
            first_handler(CreateDirectDialogCommand(actor_id=alice_id, peer_id=bob_id)),
            second_handler(
                CreateDirectDialogCommand(actor_id=bob_id, peer_id=alice_id)
            ),
        ),
        timeout=2,
    )

    assert sorted((first.created, second.created)) == [False, True]
    assert first.dialog == second.dialog
    assert tuple(item.id for item in projections.for_user(alice_id)) == (
        first.dialog.id,
    )
    assert tuple(item.id for item in projections.for_user(bob_id)) == (first.dialog.id,)


@pytest.mark.asyncio
async def test_concurrent_saved_creators_receive_the_same_owner_dialog(
    alice_id: UUID, registered_users, projections, clock, ids
) -> None:
    repository = ConcurrentSavedDialogs()
    first_handler = CreateSavedDialogHandler(
        repository, projections, registered_users, clock.now, ids.new_id
    )
    second_handler = CreateSavedDialogHandler(
        repository, projections, registered_users, clock.now, ids.new_id
    )
    command = CreateSavedDialogCommand(actor_id=alice_id)
    first, second = await asyncio.wait_for(
        asyncio.gather(first_handler(command), second_handler(command)), timeout=2
    )

    assert sorted((first.created, second.created)) == [False, True]
    assert first.dialog == second.dialog
    assert tuple(item.id for item in projections.for_user(alice_id)) == (
        first.dialog.id,
    )
