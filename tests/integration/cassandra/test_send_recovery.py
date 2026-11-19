from datetime import UTC, datetime
from uuid import uuid7

import pytest
from cassandra import OperationTimedOut

from app.application.exceptions.dependencies import StorageUnavailableError
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.infrastructure.persistence.cassandra.dialogues import CassandraDirectDialogs
from app.infrastructure.persistence.cassandra.messages import CassandraMessages

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.mark.asyncio
async def test_accepted_send_recovers_history_sync_and_outbox_after_restart(
    cassandra_session, monkeypatch
):
    from app.infrastructure.persistence.cassandra.outbox import CassandraOutbox
    from app.infrastructure.persistence.cassandra.views import CassandraMessageViews

    sender, recipient = uuid7(), uuid7()
    dialog = DirectDialog.create(
        participants=DirectParticipants.from_user_ids(sender, recipient), now=NOW
    )
    await CassandraDirectDialogs(cassandra_session).create_or_get(dialog)
    message = Message.create(
        dialog_id=dialog.id,
        sender_id=sender,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="После сбоя", attachments=()),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        now=NOW,
    )
    native_execute = cassandra_session.execute_async

    def unavailable_history(query, *args, **kwargs):
        if "INSERT INTO message_history" in str(query):
            raise OperationTimedOut()
        return native_execute(query, *args, **kwargs)

    monkeypatch.setattr(cassandra_session, "execute_async", unavailable_history)
    with pytest.raises(StorageUnavailableError):
        await CassandraMessages(cassandra_session).save_message(
            message, idempotency_key=message.send_key
        )
    monkeypatch.setattr(cassandra_session, "execute_async", native_execute)

    restarted = CassandraMessages(cassandra_session)
    assert await restarted.repair_pending(limit=10) == 1
    replay = await restarted.get_by_send_key(message.send_key)
    assert replay is not None
    assert replay.id == message.id
    assert replay.position.value == 1
    assert await restarted.get_last_position(dialog.id) == 1
    views = CassandraMessageViews(cassandra_session)
    history = await views.history(dialog.id, after=0, through=1, limit=10)
    assert [item.text_value for item in history] == ["После сбоя"]
    for actor in (sender, recipient):
        events = await views.sync(actor, after=0, through=None, limit=10)
        sends = [item for item in events.items if item.message is not None]
        assert len(sends) == 1
        assert sends[0].message.id == message.id
    outbox = CassandraOutbox(cassandra_session, clock=lambda: NOW)
    claimed = await outbox.claim_batch(
        owner_token=uuid7(),
        claimed_at=NOW,
        claim_expires_at=NOW.replace(hour=1),
        limit=10,
    )
    assert {item.type for item in claimed} == {
        "message.persisted.v1",
        "message.created.v1",
    }
    original_envelopes = {item.id: item.payload for item in claimed}
    assert await restarted.repair_pending(limit=10) == 0
    assert await restarted.get_by_send_key(message.send_key) == replay
    assert {item.id: item.payload for item in claimed} == original_envelopes
