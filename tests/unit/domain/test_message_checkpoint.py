from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domain import MessageCheckpoint, MessagePosition
from app.domain.exceptions import InvalidDomainTimestampError


def test_checkpoint_creation_and_properties(now: datetime) -> None:
    pos = MessagePosition(value=100)
    cp = MessageCheckpoint(position=pos, timestamp=now)

    assert cp.position == pos
    assert cp.timestamp == now


def test_checkpoint_factory_supports_raw_int(now: datetime) -> None:
    cp = MessageCheckpoint.create(position=100, timestamp=now)

    assert cp.position == MessagePosition(value=100)
    assert cp.timestamp == now


def test_checkpoint_normalizes_timezone_to_utc(now: datetime) -> None:
    local_time = now.astimezone(timezone(timedelta(hours=3)))
    cp = MessageCheckpoint.create(position=100, timestamp=local_time)

    assert cp.timestamp == now
    assert cp.timestamp.tzinfo is UTC


def test_checkpoint_rejects_naive_timestamp() -> None:
    with pytest.raises(InvalidDomainTimestampError):
        MessageCheckpoint.create(position=100, timestamp=datetime(2026, 9, 21, 3, 0))


def test_checkpoint_ordering_delegates_to_position(now: datetime) -> None:
    cp1 = MessageCheckpoint.create(position=10, timestamp=now)
    cp2 = MessageCheckpoint.create(position=20, timestamp=now - timedelta(seconds=10))

    assert cp1 < cp2
    assert cp1 <= cp2
    assert cp2 > cp1
    assert cp2 >= cp1


def test_checkpoint_comparison_with_incompatible_type_raises_type_error(
    now: datetime,
) -> None:
    cp = MessageCheckpoint.create(position=10, timestamp=now)
    with pytest.raises(TypeError):
        _ = cp < 10


def test_checkpoint_is_frozen(now: datetime) -> None:
    cp = MessageCheckpoint.create(position=10, timestamp=now)
    with pytest.raises(ValidationError) as exc_info:
        cp.position = MessagePosition(value=20)
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"
