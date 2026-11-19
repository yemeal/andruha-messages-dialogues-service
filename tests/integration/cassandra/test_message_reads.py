from datetime import UTC, datetime
from uuid import uuid7

import pytest

from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition
from app.infrastructure.persistence.cassandra.views import CassandraMessageViews


@pytest.mark.asyncio
async def test_history_crosses_position_bucket_without_duplicates_or_late_insert(
    cassandra_session,
):
    dialog_id, sender = uuid7(), uuid7()
    views = CassandraMessageViews(cassandra_session)
    for position in (255, 256, 257, 258, 259):
        message = Message.create(
            dialog_id=dialog_id,
            sender_id=sender,
            client_message_id=ClientMessageId.from_uuid(uuid7()),
            content=MessageContent.from_parts(text=str(position), attachments=()),
            position=MessagePosition(dialog_id=dialog_id, value=position),
            now=datetime(2026, 11, 17, tzinfo=UTC),
        )
        await views.store_message(message)
    first = await views.history(dialog_id, after=254, through=258, limit=2)
    second = await views.history(dialog_id, after=256, through=258, limit=2)
    assert [item.position.value for item in first] == [255, 256]
    assert [item.position.value for item in second] == [257, 258]
    assert await views.get_message(dialog_id, second[0].id) == second[0]
