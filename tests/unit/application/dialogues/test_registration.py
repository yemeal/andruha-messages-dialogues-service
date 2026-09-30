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
from app.application.exceptions.dependencies import IdentityUnavailableError
from app.application.exceptions.dialogues import UserNotRegisteredError
from app.domain.exceptions.dialogues import SelfDialogNotAllowedError


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["actor", "peer"])
async def test_unfinished_registration_prevents_direct_creation(
    direct_creation: CreateDirectDialogHandler,
    alice_id: UUID,
    bob_id: UUID,
    registered_users,
    direct_dialogs,
    projections,
    missing: str,
) -> None:
    missing_id = alice_id if missing == "actor" else bob_id
    registered_users.users -= {missing_id}

    with pytest.raises(UserNotRegisteredError) as error:
        await direct_creation(
            CreateDirectDialogCommand(actor_id=alice_id, peer_id=bob_id)
        )

    assert error.value.user_id == missing_id
    assert direct_dialogs.dialogs == {}
    assert projections.for_user(alice_id) == ()
    assert projections.for_user(bob_id) == ()


@pytest.mark.asyncio
async def test_unfinished_registration_prevents_saved_creation(
    saved_creation: CreateSavedDialogHandler,
    alice_id: UUID,
    registered_users,
    saved_dialogs,
    projections,
) -> None:
    registered_users.users = frozenset()

    with pytest.raises(UserNotRegisteredError):
        await saved_creation(CreateSavedDialogCommand(actor_id=alice_id))

    assert saved_dialogs.dialogs == {}
    assert projections.for_user(alice_id) == ()


class UnavailableIdentity:
    async def require_registered(self, user_id: UUID) -> None:
        raise IdentityUnavailableError("Identity did not return a trusted result")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["direct", "saved"])
async def test_identity_unavailability_is_not_a_negative_registration_result(
    alice_id: UUID,
    bob_id: UUID,
    direct_dialogs,
    saved_dialogs,
    projections,
    clock,
    ids,
    kind: str,
) -> None:
    with pytest.raises(IdentityUnavailableError):
        if kind == "direct":
            handler = CreateDirectDialogHandler(
                direct_dialogs,
                projections,
                UnavailableIdentity(),
                clock.now,
                ids.new_id,
            )
            await handler(CreateDirectDialogCommand(actor_id=alice_id, peer_id=bob_id))
        else:
            handler = CreateSavedDialogHandler(
                saved_dialogs,
                projections,
                UnavailableIdentity(),
                clock.now,
                ids.new_id,
            )
            await handler(CreateSavedDialogCommand(actor_id=alice_id))

    assert direct_dialogs.dialogs == {}
    assert saved_dialogs.dialogs == {}
    assert projections.for_user(alice_id) == ()


@pytest.mark.asyncio
async def test_self_dialog_is_rejected_before_any_creation(
    direct_creation: CreateDirectDialogHandler,
    alice_id: UUID,
    direct_dialogs,
    projections,
) -> None:
    with pytest.raises(SelfDialogNotAllowedError):
        await direct_creation(
            CreateDirectDialogCommand(actor_id=alice_id, peer_id=alice_id)
        )

    assert direct_dialogs.dialogs == {}
    assert projections.for_user(alice_id) == ()
