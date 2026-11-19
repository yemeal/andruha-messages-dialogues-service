import asyncio
import math
from uuid import UUID

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.exceptions.dependencies import IdentityUnavailableError
from app.application.exceptions.dialogues import UserNotRegisteredError

MAX_BATCH_SIZE = 100
MAX_RESPONSE_BYTES = 16_384


class _AccountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registered_user_ids: tuple[UUID, ...] = Field(
        alias="registeredUserIds", max_length=MAX_BATCH_SIZE
    )


class HTTPRegisteredUsers:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        service_token: str,
        timeout_seconds: float = 2.0,
    ) -> None:
        if not service_token.strip():
            raise ValueError("Identity service credential is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Identity timeout must be finite and positive")
        self._client = client
        self._service_token = service_token
        self._timeout = timeout_seconds

    async def require_registered(self, user_id: UUID) -> None:
        await self.require_registered_many((user_id,))

    async def require_registered_many(self, user_ids: tuple[UUID, ...]) -> None:
        unique = tuple(dict.fromkeys(user_ids))
        for offset in range(0, len(unique), MAX_BATCH_SIZE):
            batch = unique[offset : offset + MAX_BATCH_SIZE]
            registered = await self._lookup(batch)
            for user_id in batch:
                if user_id not in registered:
                    raise UserNotRegisteredError(user_id)

    async def _lookup(self, user_ids: tuple[UUID, ...]) -> frozenset[UUID]:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "POST",
                    "/internal/v1/accounts/lookup",
                    headers={"X-Service-Token": self._service_token},
                    json={"userIds": [str(user_id) for user_id in user_ids]},
                ) as response:
                    if response.status_code != 200:
                        raise IdentityUnavailableError("Identity lookup unavailable")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise IdentityUnavailableError(
                                "Identity response exceeds limit"
                            )
                        data.extend(chunk)
                    result = _AccountsResponse.model_validate_json(data)
        except (httpx2.HTTPError, OSError, TimeoutError, ValidationError) as error:
            raise IdentityUnavailableError("Identity lookup unavailable") from error
        registered = frozenset(result.registered_user_ids)
        if len(registered) != len(result.registered_user_ids) or not registered <= set(
            user_ids
        ):
            raise IdentityUnavailableError("Invalid Identity lookup response")
        return registered
