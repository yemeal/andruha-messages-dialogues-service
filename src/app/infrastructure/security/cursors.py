"""Signed continuations bind actor, resource, ordering, snapshot and expiry."""

import base64
import hashlib
import hmac
import time
from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_CURSOR_LENGTH = 2048
CURSOR_LIFETIME_SECONDS = 30 * 24 * 60 * 60


class InvalidCursorError(Exception):
    pass


class ExpiredCursorError(InvalidCursorError):
    pass


class Continuation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: UUID
    scope: str
    after: int = Field(ge=0)
    through: int | None = Field(default=None, ge=0)
    expires_at: int


class CursorCodec:
    def __init__(
        self,
        key: bytes,
        *,
        clock: Callable[[], float] = time.time,
        lifetime_seconds: int = CURSOR_LIFETIME_SECONDS,
    ) -> None:
        if len(key) < 32 or lifetime_seconds < 1:
            raise ValueError(
                "Cursor signing requires a 32-byte key and positive lifetime"
            )
        self.key = key
        self.clock = clock
        self.lifetime = lifetime_seconds

    def encode(
        self, actor_id: UUID, scope: str, *, after: int, through: int | None
    ) -> str:
        data = (
            Continuation(
                actor_id=actor_id,
                scope=scope,
                after=after,
                through=through,
                expires_at=int(self.clock()) + self.lifetime,
            )
            .model_dump_json()
            .encode()
        )
        signature = hmac.digest(self.key, data, hashlib.sha256)
        return base64.urlsafe_b64encode(data + signature).decode().rstrip("=")

    def decode(self, token: str, actor_id: UUID, scope: str) -> Continuation:
        try:
            if not token or len(token) > MAX_CURSOR_LENGTH:
                raise InvalidCursorError()
            raw = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            data, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(
                signature, hmac.digest(self.key, data, hashlib.sha256)
            ):
                raise InvalidCursorError()
            cursor = Continuation.model_validate_json(data)
            if (
                cursor.actor_id != actor_id
                or cursor.scope != scope
                or (cursor.through is not None and cursor.after > cursor.through)
            ):
                raise InvalidCursorError()
            if cursor.expires_at <= self.clock():
                raise ExpiredCursorError()
            return cursor
        except (ValueError, ValidationError) as error:
            raise InvalidCursorError() from error
