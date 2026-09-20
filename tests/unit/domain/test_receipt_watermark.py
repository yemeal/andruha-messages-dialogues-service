from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain import (
    MessageCheckpoint,
    ReceiptWatermark,
)
from app.domain.clock import utc_now
from app.domain.exceptions import ReadCheckpointExceedsDeliveredError


@pytest.fixture
def empty_watermark(dialog_id: UUID, alice_id: UUID, now: datetime) -> ReceiptWatermark:
    return ReceiptWatermark.create_empty(dialog_id=dialog_id, user_id=alice_id, now=now)


def test_create_empty_initializes_valid_watermark(
    dialog_id: UUID, alice_id: UUID, now: datetime
) -> None:
    watermark = ReceiptWatermark.create_empty(
        dialog_id=dialog_id, user_id=alice_id, now=now
    )

    assert isinstance(watermark.id, UUID)
    assert watermark.id.version == 7
    assert watermark.dialog_id == dialog_id
    assert watermark.user_id == alice_id
    assert watermark.delivered_through is None
    assert watermark.read_through is None
    assert watermark.version == 1
    assert watermark.created_at == now
    assert watermark.updated_at == now


def test_create_empty_generates_default_uuidv7_and_utc_time(
    dialog_id: UUID, alice_id: UUID
) -> None:
    before = utc_now()
    watermark = ReceiptWatermark.create_empty(dialog_id=dialog_id, user_id=alice_id)
    after = utc_now()

    assert isinstance(watermark.id, UUID)
    assert watermark.id.version == 7
    assert watermark.created_at.tzinfo is UTC
    assert before <= watermark.created_at <= after


def test_advance_delivered_moves_boundary_and_bumps_version(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    cp1 = MessageCheckpoint.create(position=10, timestamp=now)
    later = now + timedelta(seconds=1)

    changed = empty_watermark.advance_delivered(cp1, now=later)

    assert changed is True
    assert empty_watermark.version == 2
    assert empty_watermark.delivered_through == cp1
    assert empty_watermark.read_through is None
    assert empty_watermark.updated_at == later


def test_advance_delivered_with_stale_or_equal_checkpoint_is_noop(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    cp1 = MessageCheckpoint.create(position=10, timestamp=now)
    empty_watermark.advance_delivered(cp1, now=now + timedelta(seconds=1))

    # Duplicate ack
    changed = empty_watermark.advance_delivered(cp1, now=now + timedelta(seconds=2))
    assert changed is False
    assert empty_watermark.version == 2

    # Stale ack (smaller position)
    stale_cp = MessageCheckpoint.create(position=5, timestamp=now)
    changed_stale = empty_watermark.advance_delivered(
        stale_cp, now=now + timedelta(seconds=3)
    )
    assert changed_stale is False
    assert empty_watermark.version == 2
    assert empty_watermark.delivered_through == cp1


def test_advance_read_automatically_pulls_delivered_boundary(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    cp1 = MessageCheckpoint.create(position=10, timestamp=now)
    later = now + timedelta(seconds=1)

    # When delivered is None, advancing read pulls delivered to same checkpoint
    changed = empty_watermark.advance_read(cp1, now=later)

    assert changed is True
    assert empty_watermark.version == 2
    assert empty_watermark.read_through == cp1
    assert empty_watermark.delivered_through == cp1
    assert empty_watermark.updated_at == later


def test_advance_read_pulls_delivered_only_if_read_exceeds_delivered(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    cp_delivered = MessageCheckpoint.create(position=50, timestamp=now)
    empty_watermark.advance_delivered(cp_delivered, now=now + timedelta(seconds=1))
    assert empty_watermark.version == 2

    # Read advances to position 20 (< 50) -> delivered stays at 50
    cp_read = MessageCheckpoint.create(position=20, timestamp=now)
    changed = empty_watermark.advance_read(cp_read, now=now + timedelta(seconds=2))

    assert changed is True
    assert empty_watermark.version == 3
    assert empty_watermark.read_through == cp_read
    assert empty_watermark.delivered_through == cp_delivered

    # Read advances to position 60 (> 50) -> delivered is pulled to 60
    cp_read_ahead = MessageCheckpoint.create(position=60, timestamp=now)
    changed_ahead = empty_watermark.advance_read(
        cp_read_ahead, now=now + timedelta(seconds=3)
    )

    assert changed_ahead is True
    assert empty_watermark.version == 4
    assert empty_watermark.read_through == cp_read_ahead
    assert empty_watermark.delivered_through == cp_read_ahead


def test_advance_read_with_stale_or_equal_checkpoint_is_noop(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    cp1 = MessageCheckpoint.create(position=10, timestamp=now)
    empty_watermark.advance_read(cp1, now=now + timedelta(seconds=1))

    # Duplicate read
    changed = empty_watermark.advance_read(cp1, now=now + timedelta(seconds=2))
    assert changed is False
    assert empty_watermark.version == 2

    # Stale read (position 5 < 10)
    stale_cp = MessageCheckpoint.create(position=5, timestamp=now)
    changed_stale = empty_watermark.advance_read(
        stale_cp, now=now + timedelta(seconds=3)
    )
    assert changed_stale is False
    assert empty_watermark.version == 2
    assert empty_watermark.read_through == cp1


def test_invariant_read_cannot_exceed_delivered_on_reconstitution(
    now: datetime, dialog_id: UUID, alice_id: UUID
) -> None:
    cp_small = MessageCheckpoint.create(position=10, timestamp=now)
    cp_large = MessageCheckpoint.create(position=20, timestamp=now)

    # read > delivered must fail
    with pytest.raises(ReadCheckpointExceedsDeliveredError):
        ReceiptWatermark.model_validate(
            {
                "id": "01995140-0000-7000-8000-000000000001",
                "dialog_id": dialog_id,
                "user_id": alice_id,
                "delivered_through": cp_small.model_dump(),
                "read_through": cp_large.model_dump(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
        )

    # read without delivered must fail
    with pytest.raises(ReadCheckpointExceedsDeliveredError):
        ReceiptWatermark.model_validate(
            {
                "id": "01995140-0000-7000-8000-000000000001",
                "dialog_id": dialog_id,
                "user_id": alice_id,
                "delivered_through": None,
                "read_through": cp_large.model_dump(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
        )


def test_restoration_roundtrip_preserves_snapshot(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    cp = MessageCheckpoint.create(position=42, timestamp=now)
    empty_watermark.advance_read(cp, now=now + timedelta(seconds=1))

    dump = empty_watermark.model_dump()
    restored = ReceiptWatermark.model_validate(dump)

    assert restored == empty_watermark
    assert restored.version == empty_watermark.version
    assert restored.delivered_through == empty_watermark.delivered_through
    assert restored.read_through == empty_watermark.read_through


def test_watermark_is_frozen_against_direct_mutation(
    empty_watermark: ReceiptWatermark,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        empty_watermark.version = 10
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"


def test_is_delivered_and_is_read_query_methods(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    # On empty watermark: everything is False
    assert empty_watermark.is_delivered(10) is False
    assert empty_watermark.is_read(10) is False

    # Delivered up to 50
    cp_50 = MessageCheckpoint.create(position=50, timestamp=now)
    empty_watermark.advance_delivered(cp_50, now=now + timedelta(seconds=1))

    assert empty_watermark.is_delivered(10) is True
    assert empty_watermark.is_delivered(50) is True
    assert empty_watermark.is_delivered(51) is False
    assert empty_watermark.is_delivered(cp_50) is True
    assert empty_watermark.is_delivered(cp_50.position) is True
    assert empty_watermark.is_read(50) is False

    # Read up to 30
    cp_30 = MessageCheckpoint.create(position=30, timestamp=now)
    empty_watermark.advance_read(cp_30, now=now + timedelta(seconds=2))

    assert empty_watermark.is_read(10) is True
    assert empty_watermark.is_read(30) is True
    assert empty_watermark.is_read(31) is False
    assert empty_watermark.is_read(cp_30) is True
    assert empty_watermark.is_read(cp_30.position) is True
    assert empty_watermark.is_delivered(50) is True
