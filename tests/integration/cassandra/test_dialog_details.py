from datetime import UTC, datetime
from uuid import uuid7

import pytest

from app.application.queries.messages import MessageQueries
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.infrastructure.persistence.cassandra.dialogues import (
    CassandraDirectDialogs,
    CassandraSavedDialogs,
)
from app.infrastructure.persistence.cassandra.messages import CassandraMessages


@pytest.mark.asyncio
async def test_dialog_details_preserve_current_activity_after_creation_replay(
    cassandra_session,
):
    now = datetime(2026, 11, 17, tzinfo=UTC)
    sender, peer = uuid7(), uuid7()
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(sender, peer), now=now
    )
    direct = CassandraDirectDialogs(cassandra_session)
    await direct.create_or_get(dialog)
    messages = CassandraMessages(cassandra_session)
    message = Message.create(
        dialog_id=dialog.id,
        sender_id=sender,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Текущая карточка", attachments=()),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=now,
    )
    await messages.save_message(message, idempotency_key=message.send_key)
    await messages.views.ensure_for_user(peer, dialog)
    queries = MessageQueries(
        direct, CassandraSavedDialogs(cassandra_session), messages, messages.views
    )
    result = await queries.detail(peer, dialog.id)
    assert result.last_position == 1
    assert result.last_message is not None
    assert result.last_message.id == message.id
    assert result.last_message.text == "Текущая карточка"
