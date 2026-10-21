from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest

from app.application.ports.dto.outbox import (
    OutboxKind,
    OutboxMessage,
    OutboxStatus,
)


def test_create_pending_outbox_message() -> None:
    now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)
    key = str(uuid7())
    payload = {"foo": "bar"}

    msg = OutboxMessage(
        kind=OutboxKind.EVENT,
        topic="messages.events",
        key=key,
        type="message.created.v1",
        payload=payload,
        created_at=now,
        available_at=now,
    )

    assert isinstance(msg.id, UUID)
    assert msg.id.version == 7
    assert msg.kind is OutboxKind.EVENT
    assert msg.topic == "messages.events"
    assert msg.key == key
    assert msg.type == "message.created.v1"
    assert msg.payload == payload
    assert msg.status is OutboxStatus.PENDING
    assert msg.attempts == 0
    assert msg.claim_token is None
    assert msg.claim_expires_at is None
    assert msg.terminal_at is None


def test_outbox_message_claimed_requires_token_and_expiration() -> None:
    now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)
    claim_token = uuid7()

    with pytest.raises(ValueError, match="requires a live claim"):
        OutboxMessage(
            kind=OutboxKind.EVENT,
            topic="messages.events",
            key="k1",
            type="message.created.v1",
            payload={},
            status=OutboxStatus.CLAIMED,
            created_at=now,
            available_at=now,
        )

    msg = OutboxMessage(
        kind=OutboxKind.EVENT,
        topic="messages.events",
        key="k1",
        type="message.created.v1",
        payload={},
        status=OutboxStatus.CLAIMED,
        claim_token=claim_token,
        claim_expires_at=now + timedelta(seconds=30),
        created_at=now,
        available_at=now,
    )
    assert msg.status is OutboxStatus.CLAIMED
    assert msg.claim_token == claim_token


def test_outbox_message_terminal_requires_terminal_at() -> None:
    now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="requires terminal_at"):
        OutboxMessage(
            kind=OutboxKind.EVENT,
            topic="messages.events",
            key="k1",
            type="message.created.v1",
            payload={},
            status=OutboxStatus.SUCCESS,
            created_at=now,
            available_at=now,
        )

    msg = OutboxMessage(
        kind=OutboxKind.EVENT,
        topic="messages.events",
        key="k1",
        type="message.created.v1",
        payload={},
        status=OutboxStatus.SUCCESS,
        terminal_at=now,
        created_at=now,
        available_at=now,
    )
    assert msg.status is OutboxStatus.SUCCESS
    assert msg.terminal_at == now

    quarantined = OutboxMessage(
        kind=OutboxKind.EVENT,
        topic="messages.events",
        key="k1",
        type="message.created.v1",
        payload={},
        status=OutboxStatus.QUARANTINED,
        terminal_at=now,
        created_at=now,
        available_at=now,
    )
    assert quarantined.status is OutboxStatus.QUARANTINED
    assert quarantined.terminal_at == now


def test_outbox_message_rejects_naive_timestamps() -> None:
    naive = datetime(2026, 10, 22, 10, 0, 0)
    utc = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="created_at must be timezone-aware"):
        OutboxMessage(
            kind=OutboxKind.EVENT,
            topic="messages.events",
            key="k1",
            type="message.created.v1",
            payload={},
            created_at=naive,
            available_at=utc,
        )

    with pytest.raises(ValueError, match="available_at must be timezone-aware"):
        OutboxMessage(
            kind=OutboxKind.EVENT,
            topic="messages.events",
            key="k1",
            type="message.created.v1",
            payload={},
            created_at=utc,
            available_at=naive,
        )
