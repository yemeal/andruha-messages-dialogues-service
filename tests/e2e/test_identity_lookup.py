import os
import secrets
from uuid import UUID, uuid7

import httpx2
import pytest

from app.application.exceptions.dependencies import IdentityUnavailableError
from app.application.exceptions.dialogues import UserNotRegisteredError
from app.infrastructure.identity.registered_users import HTTPRegisteredUsers


@pytest.mark.asyncio
async def test_real_identity_registration_is_consumed_by_messages_adapter():
    url = os.environ["ANDRUHA_TEST_IDENTITY_URL"]
    token = os.environ["ANDRUHA_TEST_IDENTITY_INTERNAL_TOKEN"]
    async with httpx2.AsyncClient(base_url=url, timeout=10) as client:
        registration = await client.post(
            "/api/v1/auth/register",
            headers={"Idempotency-Key": str(uuid7())},
            json={
                "email": f"messages-lookup-{uuid7()}@example.com",
                "password": "Lookup-" + secrets.token_hex(16),
            },
        )
        assert registration.status_code == 201
        user_id = UUID(registration.json()["userId"])
        adapter = HTTPRegisteredUsers(client, service_token=token)
        await adapter.require_registered(user_id)
        with pytest.raises(UserNotRegisteredError):
            await adapter.require_registered(uuid7())
        wrong_credential = HTTPRegisteredUsers(
            client, service_token="incorrect-credential"
        )
        with pytest.raises(IdentityUnavailableError):
            await wrong_credential.require_registered(user_id)
