from datetime import UTC, datetime
from uuid import uuid7

import pytest

from app.application.commands.dialogues.send_direct_message.command import (
    SendDirectMessageCommand,
)
from app.application.commands.dialogues.send_direct_message.handler import (
    SendDirectMessageHandler,
)
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_send_key import MessageSendKey
from app.infrastructure.persistence.cassandra.dialogues import CassandraDirectDialogs

NOW = datetime(2026, 11, 17, tzinfo=UTC)


class NoAttachments:
    async def require_ready(self, actor_id, attachments):
        raise AssertionError("Text sends do not require Object Storage")


@pytest.mark.asyncio
async def test_direct_send_is_durable_and_replays_same_identity(cassandra_session):
    from app.infrastructure.persistence.cassandra.messages import CassandraMessages

    sender, recipient = uuid7(), uuid7()
    dialogs = CassandraDirectDialogs(cassandra_session)
    canonical = await dialogs.create_or_get(
        DirectDialog.create(
            participants=DirectParticipants.from_user_ids(sender, recipient), now=NOW
        )
    )
    command = SendDirectMessageCommand(
        actor_id=sender,
        dialog_id=canonical.dialog.id,
        client_message_id=uuid7(),
        text="Первое сообщение",
        attachment_ids=(),
    )
    first = await SendDirectMessageHandler(
        dialogs,
        CassandraMessages(cassandra_session),
        NoAttachments(),
        lambda: NOW,
        uuid7,
    )(command)
    restarted = CassandraMessages(cassandra_session)
    replay = await SendDirectMessageHandler(
        dialogs, restarted, NoAttachments(), lambda: NOW, uuid7
    )(command)

    assert first.message.position == 1
    assert first.message.text == "Первое сообщение"
    assert replay == first
    stored = await restarted.get_by_send_key(
        MessageSendKey(
            sender_id=sender,
            client_message_id=ClientMessageId.from_uuid(command.client_message_id),
        )
    )
    assert stored is not None
    assert stored.id == first.message.id
    assert stored.position.value == 1
    assert await restarted.get_last_position(canonical.dialog.id) == 1
