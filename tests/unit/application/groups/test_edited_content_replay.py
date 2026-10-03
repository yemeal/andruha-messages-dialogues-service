from datetime import timedelta
from uuid import UUID

import pytest

from app.application.commands.groups.send_message.command import SendGroupMessageCommand


@pytest.mark.asyncio
async def test_current_text_with_the_same_send_key_replays_the_edited_message(
    send_message, groups, clock, group_id: UUID, bob_id: UUID
) -> None:
    client_message_id = UUID("01995140-0000-7000-8000-000000000702")
    accepted = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_message_id,
            text="Original text",
        )
    )
    groups.messages[accepted.message.id].edit_text(
        actor_id=bob_id,
        text="Edited text",
        now=clock.now() + timedelta(minutes=1),
    )
    revision = groups.current.revision

    replay = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_message_id,
            text="Edited text",
        )
    )

    assert replay.message.id == accepted.message.id
    assert replay.message.position == accepted.message.position
    assert replay.message.text == "Edited text"
    assert replay.message.version == 2
    assert groups.current.revision == revision + 1
    assert len(groups.messages) == 1
    assert (await groups.get_message(group_id, accepted.message.id)).text_value == (
        "Edited text"
    )
