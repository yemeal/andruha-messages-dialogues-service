from datetime import datetime, timedelta
from uuid import UUID, uuid7

from app.domain import MessageCheckpoint, MessagePosition


def test_same_message_checkpoint_keeps_same_order_when_timestamp_differs(
    dialog_id: UUID, now: datetime
) -> None:
    position = MessagePosition(dialog_id=dialog_id, value=7)
    message_id = uuid7()
    first = MessageCheckpoint.create(
        position=position, message_id=message_id, timestamp=now
    )
    restored = MessageCheckpoint.create(
        position=position,
        message_id=message_id,
        timestamp=now + timedelta(seconds=1),
    )

    assert first == restored
    assert first <= restored
    assert restored <= first
    assert not first > restored
    assert not restored > first
    assert hash(first) == hash(restored)
