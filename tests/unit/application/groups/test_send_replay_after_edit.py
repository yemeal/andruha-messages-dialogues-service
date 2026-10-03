from datetime import timedelta
from uuid import UUID

import pytest

from app.application.commands.groups.send_message.command import SendGroupMessageCommand


@pytest.mark.asyncio
async def test_original_send_replay_preserves_the_current_message_edit(
    send_message, groups, clock, group_id: UUID, bob_id: UUID
) -> None:
    command = SendGroupMessageCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        client_message_id=UUID("01995140-0000-7000-8000-000000000601"),
        text="Первоначальный текст",
    )
    accepted = await send_message(command)
    groups.messages[accepted.message.id].edit_text(
        actor_id=bob_id,
        text="Исправленный текст",
        now=clock.now() + timedelta(minutes=1),
    )

    replay = await send_message(command)

    assert replay.message.id == accepted.message.id
    assert replay.message.position == 1
    assert replay.message.text == "Исправленный текст"
    assert replay.message.version == 2
    assert replay.message.edited_at == clock.now() + timedelta(minutes=1)
    assert len(groups.messages) == 1
