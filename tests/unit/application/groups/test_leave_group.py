from uuid import UUID

import pytest

from app.application.commands.groups.leave_group.command import LeaveGroupCommand
from app.application.commands.groups.leave_group.handler import LeaveGroupHandler
from app.domain.exceptions.groups import (
    CannotRemoveOwnerError,
)


@pytest.mark.asyncio
async def test_leave_group_success(groups, bob_id: UUID, alice_id: UUID, clock) -> None:
    handler = LeaveGroupHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000f1")
    result = await handler(
        LeaveGroupCommand(
            dialog_id=groups.current.dialog.id,
            actor_id=bob_id,
            command_id=command_id,
        )
    )

    assert bob_id not in result.members
    assert alice_id in result.members
    assert groups.current.dialog.members == frozenset({alice_id})


@pytest.mark.asyncio
async def test_owner_cannot_leave_group(groups, alice_id: UUID, clock) -> None:
    handler = LeaveGroupHandler(groups=groups, clock=clock.now)

    with pytest.raises(CannotRemoveOwnerError):
        await handler(
            LeaveGroupCommand(
                dialog_id=groups.current.dialog.id,
                actor_id=alice_id,  # Alice is owner
                command_id=UUID("01995140-0000-7000-8000-0000000000f2"),
            )
        )


@pytest.mark.asyncio
async def test_leave_group_idempotency(groups, bob_id: UUID, clock) -> None:
    handler = LeaveGroupHandler(groups=groups, clock=clock.now)

    command_id = UUID("01995140-0000-7000-8000-0000000000f3")
    cmd = LeaveGroupCommand(
        dialog_id=groups.current.dialog.id,
        actor_id=bob_id,
        command_id=command_id,
    )

    first = await handler(cmd)
    second = await handler(cmd)

    assert first == second
    assert groups.current.revision == 2
