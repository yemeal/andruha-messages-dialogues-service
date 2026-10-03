from datetime import timedelta
from uuid import UUID

import pytest

from app.application.commands.groups.send_message.command import SendGroupMessageCommand


@pytest.mark.asyncio
async def test_edited_send_key_returns_current_message_for_another_text(
    send_message, groups, clock, group_id: UUID, bob_id: UUID
) -> None:
    client_id = UUID("01995140-0000-7000-8000-000000000703")
    accepted = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_id,
            text="Original text",
        )
    )
    edit_time = clock.now() + timedelta(minutes=1)
    groups.messages[accepted.message.id].edit_text(
        actor_id=bob_id, text="Edited text", now=edit_time
    )

    replay = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_id,
            text="Another text with the same key",
        )
    )

    assert replay.message.id == accepted.message.id
    assert replay.message.text == "Edited text"
    assert replay.message.version == 2
    assert replay.message.position == 1
    assert replay.message.edited_at == edit_time
    assert len(groups.messages) == 1
    assert groups.current.last_position == 1


@pytest.mark.asyncio
async def test_new_logical_send_after_edit_requires_a_new_client_id(
    send_message, groups, clock, group_id: UUID, bob_id: UUID
) -> None:
    accepted = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000705"),
            text="Original text",
        )
    )
    groups.messages[accepted.message.id].edit_text(
        actor_id=bob_id,
        text="Edited text",
        now=clock.now() + timedelta(minutes=1),
    )

    new_send = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000706"),
            text="A new message",
        )
    )

    assert new_send.message.id != accepted.message.id
    assert new_send.message.client_message_id != accepted.message.client_message_id
    assert new_send.message.text == "A new message"
    assert new_send.message.position == 2
    assert groups.messages[accepted.message.id].text_value == "Edited text"
    assert len(groups.messages) == 2
