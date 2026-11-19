from uuid import UUID

import pytest

from app.application.commands.groups.transfer_ownership.command import (
    TransferGroupOwnershipCommand,
)
from app.application.commands.groups.transfer_ownership.handler import (
    TransferGroupOwnershipHandler,
)
from app.application.exceptions.groups import (
    CannotTransferOwnershipToSelfError,
    GroupOwnershipConflictError,
)
from app.domain.exceptions.groups import (
    NotGroupMemberError,
    NotGroupOwnerError,
)


@pytest.mark.asyncio
async def test_transfer_ownership_success(
    groups, alice_id: UUID, bob_id: UUID, clock
) -> None:
    handler = TransferGroupOwnershipHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000e1")
    result = await handler(
        TransferGroupOwnershipCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=alice_id,
            new_owner_id=bob_id,
            command_id=command_id,
        )
    )

    assert result.owner_id == bob_id
    assert alice_id in result.members
    assert bob_id in result.members
    assert result.version == 2
    assert groups.current.dialog.owner_id == bob_id


@pytest.mark.asyncio
async def test_transfer_ownership_by_non_owner_raises_error(
    groups, bob_id: UUID, alice_id: UUID, clock
) -> None:
    handler = TransferGroupOwnershipHandler(groups=groups, clock=clock.now)

    with pytest.raises(NotGroupOwnerError):
        await handler(
            TransferGroupOwnershipCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=bob_id,  # Bob is not owner
                new_owner_id=alice_id,
                command_id=UUID("01995140-0000-7000-8000-0000000000e2"),
            )
        )


@pytest.mark.asyncio
async def test_transfer_ownership_to_non_member_raises_error(
    groups, alice_id: UUID, charlie_id: UUID, clock
) -> None:
    handler = TransferGroupOwnershipHandler(groups=groups, clock=clock.now)

    with pytest.raises(NotGroupMemberError):
        await handler(
            TransferGroupOwnershipCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=alice_id,
                new_owner_id=charlie_id,  # Charlie is not in members
                command_id=UUID("01995140-0000-7000-8000-0000000000e3"),
            )
        )


@pytest.mark.asyncio
async def test_transfer_ownership_to_self_raises_error(
    groups, alice_id: UUID, clock
) -> None:
    handler = TransferGroupOwnershipHandler(groups=groups, clock=clock.now)

    with pytest.raises(CannotTransferOwnershipToSelfError):
        await handler(
            TransferGroupOwnershipCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=alice_id,
                new_owner_id=alice_id,
                command_id=UUID("01995140-0000-7000-8000-0000000000e5"),
            )
        )


@pytest.mark.asyncio
async def test_transfer_ownership_idempotent_replay(
    groups, alice_id: UUID, bob_id: UUID, clock
) -> None:
    handler = TransferGroupOwnershipHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000e4")
    cmd = TransferGroupOwnershipCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=alice_id,
        new_owner_id=bob_id,
        command_id=command_id,
    )

    first = await handler(cmd)
    second = await handler(cmd)

    assert first == second
    assert groups.current.revision == 2


@pytest.mark.asyncio
async def test_transfer_ownership_command_id_conflict(
    groups, alice_id: UUID, bob_id: UUID, charlie_id: UUID, clock
) -> None:
    # Add charlie to members first
    groups.current.dialog.add_member(charlie_id, now=clock.now(), actor_id=alice_id)

    handler = TransferGroupOwnershipHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000ea")
    cmd1 = TransferGroupOwnershipCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=alice_id,
        new_owner_id=bob_id,
        command_id=command_id,
    )
    cmd2 = TransferGroupOwnershipCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=alice_id,
        new_owner_id=charlie_id,
        command_id=command_id,
    )

    await handler(cmd1)

    with pytest.raises(GroupOwnershipConflictError):
        await handler(cmd2)
