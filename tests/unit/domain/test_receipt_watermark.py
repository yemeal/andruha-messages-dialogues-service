from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from app.domain import (
    ClientMessageId,
    DirectDialog,
    DirectParticipants,
    Message,
    MessageCheckpoint,
    MessageContent,
    MessagePosition,
    ReceiptWatermark,
)
from app.domain.clock import utc_now
from app.domain.exceptions import ReadCheckpointExceedsDeliveredError
from app.domain.policies.message_posting import MessagePostingPolicy

PEER_ID = UUID("00000000-0000-4000-8000-000000000002")


def _dialog(watermark: ReceiptWatermark) -> DirectDialog:
    return DirectDialog.create(
        participants=DirectParticipants.from_user_ids(watermark.user_id, PEER_ID),
        dialog_id=watermark.dialog_id,
        now=watermark.created_at,
    )


def _incoming(watermark: ReceiptWatermark, value: int) -> Message:
    dialog = _dialog(watermark)
    return MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=PEER_ID,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text(f"Message {value}"),
        position=MessagePosition(dialog_id=dialog.id, value=value),
        now=watermark.created_at,
    )


def _checkpoint(message: Message) -> MessageCheckpoint:
    return MessageCheckpoint.create(
        position=message.position,
        message_id=message.id,
        timestamp=message.created_at,
    )


def _ack_delivered(
    watermark: ReceiptWatermark, message: Message, now: datetime
) -> bool:
    return watermark.advance_delivered(
        actor_id=watermark.user_id,
        dialog=_dialog(watermark),
        through=message,
        now=now,
    )


def _ack_read(watermark: ReceiptWatermark, message: Message, now: datetime) -> bool:
    return watermark.advance_read(
        actor_id=watermark.user_id,
        dialog=_dialog(watermark),
        through=message,
        now=now,
    )


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
    message = _incoming(empty_watermark, 10)
    cp1 = _checkpoint(message)
    later = now + timedelta(seconds=1)

    changed = _ack_delivered(empty_watermark, message, now=later)

    assert changed is True
    assert empty_watermark.version == 2
    assert empty_watermark.delivered_through == cp1
    assert empty_watermark.read_through is None
    assert empty_watermark.updated_at == later


def test_advance_delivered_with_stale_or_equal_checkpoint_is_noop(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    message = _incoming(empty_watermark, 10)
    cp1 = _checkpoint(message)
    _ack_delivered(empty_watermark, message, now=now + timedelta(seconds=1))

    # Duplicate ack
    changed = _ack_delivered(empty_watermark, message, now=now + timedelta(seconds=2))
    assert changed is False
    assert empty_watermark.version == 2

    # Stale ack (smaller position)
    stale_message = _incoming(empty_watermark, 5)
    changed_stale = _ack_delivered(
        empty_watermark, stale_message, now=now + timedelta(seconds=3)
    )
    assert changed_stale is False
    assert empty_watermark.version == 2
    assert empty_watermark.delivered_through == cp1


def test_advance_read_automatically_pulls_delivered_boundary(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    message = _incoming(empty_watermark, 10)
    cp1 = _checkpoint(message)
    later = now + timedelta(seconds=1)

    # When delivered is None, advancing read pulls delivered to same checkpoint
    changed = _ack_read(empty_watermark, message, now=later)

    assert changed is True
    assert empty_watermark.version == 2
    assert empty_watermark.read_through == cp1
    assert empty_watermark.delivered_through == cp1
    assert empty_watermark.updated_at == later


def test_advance_read_pulls_delivered_only_if_read_exceeds_delivered(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    delivered_message = _incoming(empty_watermark, 50)
    cp_delivered = _checkpoint(delivered_message)
    _ack_delivered(empty_watermark, delivered_message, now=now + timedelta(seconds=1))
    assert empty_watermark.version == 2

    # Read advances to position 20 (< 50) -> delivered stays at 50
    read_message = _incoming(empty_watermark, 20)
    cp_read = _checkpoint(read_message)
    changed = _ack_read(empty_watermark, read_message, now=now + timedelta(seconds=2))

    assert changed is True
    assert empty_watermark.version == 3
    assert empty_watermark.read_through == cp_read
    assert empty_watermark.delivered_through == cp_delivered

    # Read advances to position 60 (> 50) -> delivered is pulled to 60
    read_ahead_message = _incoming(empty_watermark, 60)
    cp_read_ahead = _checkpoint(read_ahead_message)
    changed_ahead = _ack_read(
        empty_watermark, read_ahead_message, now=now + timedelta(seconds=3)
    )

    assert changed_ahead is True
    assert empty_watermark.version == 4
    assert empty_watermark.read_through == cp_read_ahead
    assert empty_watermark.delivered_through == cp_read_ahead


def test_advance_read_with_stale_or_equal_checkpoint_is_noop(
    empty_watermark: ReceiptWatermark, now: datetime
) -> None:
    message = _incoming(empty_watermark, 10)
    cp1 = _checkpoint(message)
    _ack_read(empty_watermark, message, now=now + timedelta(seconds=1))

    # Duplicate read
    changed = _ack_read(empty_watermark, message, now=now + timedelta(seconds=2))
    assert changed is False
    assert empty_watermark.version == 2

    # Stale read (position 5 < 10)
    stale_message = _incoming(empty_watermark, 5)
    changed_stale = _ack_read(
        empty_watermark, stale_message, now=now + timedelta(seconds=3)
    )
    assert changed_stale is False
    assert empty_watermark.version == 2
    assert empty_watermark.read_through == cp1


def test_invariant_read_cannot_exceed_delivered_on_reconstitution(
    now: datetime, dialog_id: UUID, alice_id: UUID
) -> None:
    cp_small = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=10),
        message_id=uuid7(),
        timestamp=now,
    )
    cp_large = MessageCheckpoint.create(
        position=MessagePosition(dialog_id=dialog_id, value=20),
        message_id=uuid7(),
        timestamp=now,
    )

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
    message = _incoming(empty_watermark, 42)
    _ack_read(empty_watermark, message, now=now + timedelta(seconds=1))

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
    def position(value: int) -> MessagePosition:
        return MessagePosition(dialog_id=empty_watermark.dialog_id, value=value)

    # On empty watermark: everything is False
    assert empty_watermark.is_delivered(position(10)) is False
    assert empty_watermark.is_read(position(10)) is False

    # Delivered up to 50
    delivered_message = _incoming(empty_watermark, 50)
    cp_50 = _checkpoint(delivered_message)
    _ack_delivered(empty_watermark, delivered_message, now=now + timedelta(seconds=1))

    assert empty_watermark.is_delivered(position(10)) is True
    assert empty_watermark.is_delivered(position(50)) is True
    assert empty_watermark.is_delivered(position(51)) is False
    assert empty_watermark.is_delivered(cp_50) is True
    assert empty_watermark.is_delivered(cp_50.position) is True
    assert empty_watermark.is_read(position(50)) is False

    # Read up to 30
    read_message = _incoming(empty_watermark, 30)
    cp_30 = _checkpoint(read_message)
    _ack_read(empty_watermark, read_message, now=now + timedelta(seconds=2))

    assert empty_watermark.is_read(position(10)) is True
    assert empty_watermark.is_read(position(30)) is True
    assert empty_watermark.is_read(position(31)) is False
    assert empty_watermark.is_read(cp_30) is True
    assert empty_watermark.is_read(cp_30.position) is True
    assert empty_watermark.is_delivered(position(50)) is True
