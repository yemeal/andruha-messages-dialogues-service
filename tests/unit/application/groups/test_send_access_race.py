import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.domain.aggregates.message import Message
from app.domain.exceptions.groups import NotGroupMemberError


@pytest.mark.asyncio
async def test_removed_member_cannot_commit_a_message_from_stale_group_snapshot(
    groups,
    send_message,
    remove_member,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    groups.pause_type = Message
    pending = asyncio.create_task(
        send_message(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                client_message_id=UUID("01995140-0000-7000-8000-000000000101"),
                text="Отправлено по старому составу",
            )
        )
    )
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        await remove_member(
            RemoveGroupMemberCommand(
                dialog_id=group_id, actor_id=alice_id, user_id=bob_id
            )
        )
        groups.resume.set()
        with pytest.raises(NotGroupMemberError):
            await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    assert groups.messages == {}
    assert bob_id not in groups.current.dialog
    assert groups.current.last_position == 0
