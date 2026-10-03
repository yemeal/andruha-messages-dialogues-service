import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.exceptions.groups import MessageSendConflictError
from app.domain.aggregates.message import Message
from app.domain.exceptions.groups import NotGroupMemberError


@pytest.mark.asyncio
async def test_accepted_message_is_saved_before_result_and_retry_keeps_identity(
    send_message, groups, group_id: UUID, bob_id: UUID
) -> None:
    command = SendGroupMessageCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        client_message_id=UUID("01995140-0000-7000-8000-000000000301"),
        text="Одно сообщение",
    )
    first = await send_message(command)
    second = await send_message(command)

    assert first == second
    assert first.group_version == 1
    assert first.message.position == 1
    assert first.message.sender_id == bob_id
    assert first.message.dialog_id == group_id
    assert len(groups.messages) == 1
    assert groups.current.last_position == 1
    assert await groups.get_message(group_id, first.message.id) is not None


@pytest.mark.asyncio
async def test_concurrent_messages_retry_with_distinct_increasing_positions(
    send_message, groups, group_id: UUID, alice_id: UUID, bob_id: UUID
) -> None:
    groups.pause_type = Message
    pending = asyncio.create_task(
        send_message(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                client_message_id=UUID("01995140-0000-7000-8000-000000000302"),
                text="Первый кандидат",
            )
        )
    )
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        winner = await send_message(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=alice_id,
                client_message_id=UUID("01995140-0000-7000-8000-000000000303"),
                text="Победитель первой записи",
            )
        )
        groups.resume.set()
        retried = await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    assert winner.message.position == 1
    assert retried.message.position == 2
    assert winner.message.id != retried.message.id
    assert len(groups.messages) == 2
    assert groups.current.last_position == 2
    assert groups.current.dialog.version == 1


@pytest.mark.asyncio
async def test_removed_sender_cannot_receive_success_from_old_message_replay(
    send_message, remove_member, groups, group_id: UUID, alice_id: UUID, bob_id: UUID
) -> None:
    command = SendGroupMessageCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        client_message_id=UUID("01995140-0000-7000-8000-000000000304"),
        text="Сообщение до исключения",
    )
    accepted = await send_message(command)
    await remove_member(
        RemoveGroupMemberCommand(
            command_id=UUID("01995140-0000-7000-8000-000000000781"),
            dialog_id=group_id,
            actor_id=alice_id,
            user_id=bob_id,
        )
    )
    revision = groups.current.revision

    with pytest.raises(NotGroupMemberError):
        await send_message(command)

    assert groups.current.revision == revision
    assert await groups.get_message(group_id, accepted.message.id) is not None
    assert len(groups.messages) == 1


@pytest.mark.asyncio
async def test_reusing_send_key_for_different_content_fails_without_writing(
    send_message, groups, group_id: UUID, bob_id: UUID
) -> None:
    client_id = UUID("01995140-0000-7000-8000-000000000305")
    await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_id,
            text="Первое",
        )
    )
    revision = groups.current.revision
    with pytest.raises(MessageSendConflictError):
        await send_message(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                client_message_id=client_id,
                text="Другое",
            )
        )

    assert groups.current.revision == revision
    assert len(groups.messages) == 1
