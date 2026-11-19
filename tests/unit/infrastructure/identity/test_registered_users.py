import json
from uuid import uuid7

import httpx2
import pytest

from app.application.exceptions.dependencies import IdentityUnavailableError
from app.application.exceptions.dialogues import UserNotRegisteredError
from app.infrastructure.identity.registered_users import HTTPRegisteredUsers


@pytest.mark.asyncio
async def test_identity_adapter_uses_only_completed_account_lookup():
    present, missing = uuid7(), uuid7()

    def respond(request):
        assert request.url.path == "/internal/v1/accounts/lookup"
        assert request.headers["x-service-token"] == "test-service-credential"
        user_ids = json.loads(request.content)["userIds"]
        return httpx2.Response(
            200,
            json={
                "registeredUserIds": [str(present)] if str(present) in user_ids else [],
            },
        )

    async with httpx2.AsyncClient(
        base_url="http://identity", transport=httpx2.MockTransport(respond)
    ) as client:
        adapter = HTTPRegisteredUsers(client, service_token="test-service-credential")
        await adapter.require_registered(present)
        with pytest.raises(UserNotRegisteredError):
            await adapter.require_registered(missing)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {}),
        (503, {}),
        (200, {}),
        (200, {"registeredUserIds": [str(uuid7())]}),
    ],
)
async def test_dependency_failure_or_invalid_response_is_not_unregistered(status, body):
    def respond(request):
        return httpx2.Response(status, json=body)

    async with httpx2.AsyncClient(
        base_url="http://identity", transport=httpx2.MockTransport(respond)
    ) as client:
        adapter = HTTPRegisteredUsers(client, service_token="test-service-credential")
        with pytest.raises(IdentityUnavailableError):
            await adapter.require_registered(uuid7())


@pytest.mark.asyncio
async def test_identity_transport_timeout_is_retryable_dependency_failure():
    def respond(request):
        raise httpx2.ReadTimeout("Dependency timeout", request=request)

    async with httpx2.AsyncClient(
        base_url="http://identity", transport=httpx2.MockTransport(respond)
    ) as client:
        adapter = HTTPRegisteredUsers(client, service_token="test-service-credential")
        with pytest.raises(IdentityUnavailableError):
            await adapter.require_registered(uuid7())


@pytest.mark.asyncio
async def test_many_registered_accounts_use_bounded_batches():
    batch_sizes = []

    def respond(request):
        user_ids = json.loads(request.content)["userIds"]
        batch_sizes.append(len(user_ids))
        return httpx2.Response(200, json={"registeredUserIds": user_ids})

    async with httpx2.AsyncClient(
        base_url="http://identity", transport=httpx2.MockTransport(respond)
    ) as client:
        adapter = HTTPRegisteredUsers(client, service_token="test-service-credential")
        await adapter.require_registered_many(tuple(uuid7() for _ in range(201)))
    assert batch_sizes == [100, 100, 1]
