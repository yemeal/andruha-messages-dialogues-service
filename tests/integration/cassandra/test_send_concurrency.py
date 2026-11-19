import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest

from app.application.exceptions.groups import MessageSendConflictError
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.infrastructure.persistence.cassandra.dialogues import (
    CassandraDirectDialogs,
    CassandraSavedDialogs,
)
from app.infrastructure.persistence.cassandra.messages import CassandraMessages

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.mark.asyncio
async def test_writers_allocate_consecutive_positions_and_global_send_key_conflicts(
    cassandra_session,
):
    sender, peer = uuid7(), uuid7()
    direct = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(sender, peer), now=NOW
    )
    saved = SavedDialog.create(user_id=sender, now=NOW)
    await CassandraDirectDialogs(cassandra_session).create_or_get(direct)
    await CassandraSavedDialogs(cassandra_session).create_or_get(saved)
    messages = [
        Message.create(
            dialog_id=direct.id,
            sender_id=sender,
            client_message_id=ClientMessageId.from_uuid(uuid7()),
            content=MessageContent.from_parts(
                text=f"Сообщение {index}", attachments=()
            ),
            position=MessagePosition(dialog_id=direct.id, value=1),
            now=NOW + timedelta(seconds=index),
        )
        for index in range(8)
    ]
    result = await asyncio.gather(
        *(
            CassandraMessages(cassandra_session).save_message(
                item, idempotency_key=item.send_key
            )
            for item in messages
        )
    )
    assert sorted(item.position.value for item in result) == list(range(1, 9))
    assert len({item.id for item in result}) == 8
    adapter = CassandraMessages(cassandra_session)
    replay = await asyncio.gather(
        *(
            adapter.save_message(messages[0], idempotency_key=messages[0].send_key)
            for _ in range(4)
        )
    )
    assert {item.id for item in replay} == {messages[0].id}
    assert await adapter.get_last_position(direct.id) == 8
    conflicting = messages[0].model_copy(
        update={
            "dialog_id": saved.id,
            "position": MessagePosition(dialog_id=saved.id, value=1),
        }
    )
    with pytest.raises(MessageSendConflictError):
        await adapter.save_message(conflicting, idempotency_key=conflicting.send_key)
    assert await adapter.get_last_position(saved.id) == 0
