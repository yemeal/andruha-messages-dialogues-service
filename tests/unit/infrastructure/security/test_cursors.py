from uuid import uuid7

import pytest

from app.infrastructure.security.cursors import (
    CursorCodec,
    ExpiredCursorError,
    InvalidCursorError,
)


def test_cursor_retains_position_snapshot_and_rejects_other_actor_scope_and_tampering():
    actor = uuid7()
    codec = CursorCodec(b"test-cursor-signing-key-at-least-32-bytes", clock=lambda: 100)
    token = codec.encode(actor, "history:dialog-a:asc", after=256, through=300)
    restored = codec.decode(token, actor, "history:dialog-a:asc")
    assert restored.after == 256
    assert restored.through == 300
    with pytest.raises(InvalidCursorError):
        codec.decode(token, uuid7(), "history:dialog-a:asc")
    with pytest.raises(InvalidCursorError):
        codec.decode(token, actor, "history:dialog-b:asc")
    with pytest.raises(InvalidCursorError):
        codec.decode("A" + token[1:], actor, "history:dialog-a:asc")


def test_sync_cursor_expiry_requires_new_snapshot():
    actor = uuid7()
    key = b"test-cursor-signing-key-at-least-32-bytes"
    token = CursorCodec(key, clock=lambda: 100, lifetime_seconds=10).encode(
        actor, "sync:sequence:asc", after=1, through=None
    )
    with pytest.raises(ExpiredCursorError):
        CursorCodec(key, clock=lambda: 111).decode(token, actor, "sync:sequence:asc")
