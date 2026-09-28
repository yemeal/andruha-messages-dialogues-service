from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from app.domain import MessageCheckpoint, MessagePosition
from app.domain.exceptions import DomainError, InvalidDomainTimestampError


def test_checkpoint_identifies_message_in_dialog(
    dialog_id: UUID, now: datetime
) -> None:
    message_id = uuid7()
    position = MessagePosition(dialog_id=dialog_id, value=10)

    checkpoint = MessageCheckpoint.create(
        position=position, message_id=message_id, timestamp=now
    )

    assert checkpoint.dialog_id == dialog_id
    assert checkpoint.message_id == message_id
    assert checkpoint.position == position


def test_checkpoint_creation_and_properties(dialog_id: UUID, now: datetime) -> None:
    pos = MessagePosition(dialog_id=dialog_id, value=100)
    message_id = uuid7()
    cp = MessageCheckpoint(position=pos, message_id=message_id, timestamp=now)

    assert cp.position == pos
    assert cp.message_id == message_id
    assert cp.dialog_id == dialog_id
    assert cp.timestamp == now


def test_checkpoint_rejects_unscoped_raw_position(
    dialog_id: UUID, now: datetime
) -> None:
    with pytest.raises(ValidationError):
        MessageCheckpoint.model_validate(
            {"position": 100, "message_id": uuid7(), "timestamp": now}
        )


def test_checkpoint_factory_preserves_scoped_position(
    dialog_id: UUID, now: datetime
) -> None:
    position = MessagePosition(dialog_id=dialog_id, value=100)
    cp = MessageCheckpoint.create(position=position, message_id=uuid7(), timestamp=now)

    assert cp.position == position


def test_checkpoint_normalizes_timezone_to_utc(dialog_id: UUID, now: datetime) -> None:
    local_time = now.astimezone(timezone(timedelta(hours=3)))
    cp = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=100),
        message_id=uuid7(),
        timestamp=local_time,
    )

    assert cp.timestamp == now
    assert cp.timestamp.tzinfo is UTC


def test_checkpoint_rejects_naive_timestamp(dialog_id: UUID) -> None:
    with pytest.raises(InvalidDomainTimestampError):
        MessageCheckpoint.create(
            position=MessagePosition(dialog_id=dialog_id, value=100),
            message_id=uuid7(),
            timestamp=datetime(2026, 9, 21, 3, 0),
        )


def test_checkpoint_ordering_delegates_to_position(
    dialog_id: UUID, now: datetime
) -> None:
    cp1 = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=10),
        message_id=uuid7(),
        timestamp=now,
    )
    cp2 = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=20),
        message_id=uuid7(),
        timestamp=now - timedelta(seconds=10),
    )

    assert cp1 < cp2
    assert cp1 <= cp2
    assert cp2 > cp1
    assert cp2 >= cp1


def test_same_position_cannot_identify_different_messages(
    dialog_id: UUID, now: datetime
) -> None:
    position = MessagePosition(dialog_id=dialog_id, value=10)
    first = MessageCheckpoint.create(
        position=position, message_id=uuid7(), timestamp=now
    )
    second = MessageCheckpoint.create(
        position=position, message_id=uuid7(), timestamp=now
    )

    with pytest.raises(DomainError):
        _ = first < second


def test_checkpoint_comparison_with_incompatible_type_raises_type_error(
    dialog_id: UUID,
    now: datetime,
) -> None:
    cp = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=10),
        message_id=uuid7(),
        timestamp=now,
    )
    with pytest.raises(TypeError):
        _ = cp < 10


def test_checkpoint_is_frozen(dialog_id: UUID, now: datetime) -> None:
    cp = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=10),
        message_id=uuid7(),
        timestamp=now,
    )
    with pytest.raises(ValidationError) as exc_info:
        cp.position = MessagePosition(dialog_id=dialog_id, value=20)
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"
