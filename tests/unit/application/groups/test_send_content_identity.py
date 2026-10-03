from datetime import timedelta
from uuid import UUID

import pytest

from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.commands.groups.send_message.handler import SendGroupMessageHandler
from app.application.exceptions.groups import MessageSendConflictError
from app.domain.value_objects.object_id import ObjectId

FIRST_OBJECT_ID = UUID("00000000-0000-4000-8000-000000000101")
SECOND_OBJECT_ID = UUID("00000000-0000-4000-8000-000000000102")


class ReadyAttachments:
    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        pass


@pytest.fixture
def send_with_attachments(groups, clock, ids) -> SendGroupMessageHandler:
    return SendGroupMessageHandler(groups, clock.now, ids.new_id, ReadyAttachments())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        pytest.param(
            {"text": "  Cafe\u0301\r\nmessage  "},
            {"text": "Caf\u00e9\nmessage"},
            True,
            id="normalized-text",
        ),
        pytest.param(
            {"text": "Original"}, {"text": "Different"}, False, id="different-text"
        ),
        pytest.param(
            {"text": "Caption", "attachment_ids": (FIRST_OBJECT_ID, SECOND_OBJECT_ID)},
            {"text": "Caption", "attachment_ids": (SECOND_OBJECT_ID, FIRST_OBJECT_ID)},
            False,
            id="attachment-order",
        ),
        pytest.param(
            {"attachment_ids": (FIRST_OBJECT_ID,)},
            {"text": "  ", "attachment_ids": (FIRST_OBJECT_ID,)},
            True,
            id="normalized-empty-caption",
        ),
        pytest.param(
            {"attachment_ids": (FIRST_OBJECT_ID,)},
            {"attachment_ids": (SECOND_OBJECT_ID,)},
            False,
            id="different-attachment",
        ),
    ],
)
async def test_unedited_send_key_checks_normalized_content(
    send_with_attachments,
    groups,
    group_id: UUID,
    bob_id: UUID,
    first: dict,
    second: dict,
    same: bool,
) -> None:
    identity = {
        "dialog_id": group_id,
        "actor_id": bob_id,
        "client_message_id": UUID("01995140-0000-7000-8000-000000000704"),
    }
    accepted = await send_with_attachments(SendGroupMessageCommand(**identity, **first))
    before = groups.messages[accepted.message.id].model_dump()
    revision = groups.current.revision

    if same:
        replay = await send_with_attachments(
            SendGroupMessageCommand(**identity, **second)
        )
        assert replay.message == accepted.message
    else:
        with pytest.raises(MessageSendConflictError):
            await send_with_attachments(SendGroupMessageCommand(**identity, **second))
        assert groups.current.revision == revision

    assert groups.messages[accepted.message.id].model_dump() == before
    assert len(groups.messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replay_attachments",
    [(FIRST_OBJECT_ID,), (SECOND_OBJECT_ID, FIRST_OBJECT_ID)],
    ids=["removed-attachment", "reordered-attachments"],
)
async def test_edit_does_not_allow_changing_attachments_in_send_replay(
    send_with_attachments,
    groups,
    clock,
    group_id: UUID,
    bob_id: UUID,
    replay_attachments: tuple[UUID, ...],
) -> None:
    client_id = UUID("01995140-0000-7000-8000-000000000707")
    accepted = await send_with_attachments(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_id,
            text="Original caption",
            attachment_ids=(FIRST_OBJECT_ID, SECOND_OBJECT_ID),
        )
    )
    groups.messages[accepted.message.id].edit_text(
        actor_id=bob_id,
        text="Edited caption",
        now=clock.now() + timedelta(minutes=1),
    )
    before = groups.messages[accepted.message.id].model_dump()
    revision = groups.current.revision

    with pytest.raises(MessageSendConflictError):
        await send_with_attachments(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                client_message_id=client_id,
                text="Another caption",
                attachment_ids=replay_attachments,
            )
        )

    assert groups.messages[accepted.message.id].model_dump() == before
    assert groups.current.revision == revision
    assert len(groups.messages) == 1


@pytest.mark.asyncio
async def test_normalized_no_op_edit_keeps_strict_send_content_check(
    send_with_attachments,
    groups,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    client_id = UUID("01995140-0000-7000-8000-000000000708")
    accepted = await send_with_attachments(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=client_id,
            text="Original text",
        )
    )
    changed = groups.messages[accepted.message.id].edit_text(
        actor_id=bob_id, text="  Original text  ", now=clock.now()
    )
    revision = groups.current.revision

    with pytest.raises(MessageSendConflictError):
        await send_with_attachments(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                client_message_id=client_id,
                text="Different text",
            )
        )

    assert changed is False
    assert groups.messages[accepted.message.id].version == 1
    assert groups.current.revision == revision
    assert len(groups.messages) == 1
