from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest

from app.application.events.factory import EventFactory
from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.infrastructure.persistence.cassandra.outbox import CassandraOutbox


@pytest.mark.asyncio
async def test_expired_outbox_owner_cannot_finalize_reclaimed_event(cassandra_session):
    now = datetime(2026, 11, 17, tzinfo=UTC)
    dialog_id = uuid7()
    message = Message.create(
        dialog_id=dialog_id,
        sender_id=uuid7(),
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Событие", attachments=()),
        position=MessagePosition(dialog_id=dialog_id, value=1),
        now=now,
    )
    event = EventFactory(clock=lambda: now).create_message_persisted(
        message=message, correlation_id=uuid7()
    )
    outbox = CassandraOutbox(cassandra_session, clock=lambda: now)
    await outbox.save_messages((event,))
    first_owner, second_owner = uuid7(), uuid7()
    first = await outbox.claim_batch(
        owner_token=first_owner,
        claimed_at=now,
        claim_expires_at=now + timedelta(seconds=10),
        limit=1,
    )
    assert len(first) == 1
    second = await outbox.claim_batch(
        owner_token=second_owner,
        claimed_at=now + timedelta(seconds=11),
        claim_expires_at=now + timedelta(seconds=30),
        limit=1,
    )
    assert len(second) == 1
    assert second[0].id == first[0].id == event.id
    assert second[0].payload == first[0].payload == event.payload
    assert second[0].attempts == 2
    assert not await outbox.finalize_published(
        event.id, owner_token=first_owner, published_at=now + timedelta(seconds=12)
    )
    assert await outbox.finalize_published(
        event.id, owner_token=second_owner, published_at=now + timedelta(seconds=12)
    )
    await CassandraOutbox(cassandra_session).save_messages((event,))
    assert (
        await outbox.claim_batch(
            owner_token=uuid7(),
            claimed_at=now + timedelta(seconds=40),
            claim_expires_at=now + timedelta(seconds=50),
            limit=1,
        )
        == []
    )
