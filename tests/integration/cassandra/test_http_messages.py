import json
import time
from uuid import uuid7

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.jwt import JWTSettings
from app.entrypoints.http.main import create_app
from app.infrastructure.identity.registered_users import HTTPRegisteredUsers
from app.infrastructure.security.access_tokens import AccessTokenVerifier


@pytest.mark.asyncio
async def test_verified_users_create_one_direct_and_read_text_via_history_and_sync(
    cassandra_session, tmp_path
):
    from app.infrastructure.bootstrap.messaging import MessagingRuntime
    from app.infrastructure.security.cursors import CursorCodec

    sender, recipient, outsider = uuid7(), uuid7(), uuid7()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    verifier = AccessTokenVerifier(JWTSettings(public_keys={"test": public_path}))

    def token(actor):
        return jwt.encode(
            {
                "iss": "andruha-identity-service",
                "aud": "andruha-messages-dialogues-service",
                "sub": str(actor),
                "jti": str(uuid7()),
                "role": "USER",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"typ": "at+jwt", "kid": "test"},
        )

    identity_requests = []

    def lookup(request):
        identity_requests.append(request)
        return httpx2.Response(
            200,
            json={
                "registeredUserIds": [
                    value
                    for value in json.loads(request.content)["userIds"]
                    if value in {str(sender), str(recipient)}
                ]
            },
        )

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lookup), base_url="http://identity"
    ) as identity:
        runtime = MessagingRuntime(
            cassandra_session,
            HTTPRegisteredUsers(identity, service_token="integration-credential"),
            verifier,
            CursorCodec(b"integration-cursor-secret-32-bytes-minimum"),
        )
        app = create_app(runtime=runtime)
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://messages"
            ) as client,
        ):
            a = {"Authorization": "Bearer " + token(sender)}
            b = {"Authorization": "Bearer " + token(recipient)}
            c = {"Authorization": "Bearer " + token(outsider)}
            created = await client.post(
                "/api/v1/dialogues/direct",
                headers=a,
                json={"peerId": str(recipient)},
            )
            assert created.status_code == 201, created.text
            dialog_id = created.json()["dialog"]["dialogId"]
            reversed_pair = await client.post(
                "/api/v1/dialogues/direct", headers=b, json={"peerId": str(sender)}
            )
            assert reversed_pair.status_code == 200
            assert reversed_pair.json()["dialog"]["dialogId"] == dialog_id
            before_sends = len(identity_requests)
            path = f"/api/v1/dialogues/{dialog_id}/messages"
            body = {"clientMessageId": str(uuid7()), "text": "Привет через HTTP"}
            sent = await client.post(path, headers=a, json=body)
            assert sent.status_code == 200, sent.text
            replay = await client.post(path, headers=a, json=body)
            assert replay.status_code == 200
            assert replay.json() == sent.json()
            assert sent.json()["message"]["position"] == 1
            history = await client.get(path, headers=b)
            assert history.status_code == 200
            assert [item["text"] for item in history.json()["items"]] == [
                "Привет через HTTP"
            ]
            sync = await client.get("/api/v1/dialogues/sync", headers=b)
            assert sync.status_code == 200
            sends = [item for item in sync.json()["items"] if item.get("message")]
            assert len(sends) == 1
            assert (
                sends[0]["message"]["messageId"] == sent.json()["message"]["messageId"]
            )
            quiet = await client.get(
                "/api/v1/dialogues/sync",
                headers=b,
                params={"cursor": sync.json()["cursor"]},
            )
            assert quiet.status_code == 200
            assert quiet.json()["items"] == []
            assert len(identity_requests) == before_sends
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers=c)).status_code == 404
            assert (
                await client.post(
                    path, headers=a, json=body | {"actorId": str(recipient)}
                )
            ).status_code == 422
            assert (
                await client.get(
                    "/api/v1/dialogues/sync",
                    headers=a,
                    params={"cursor": sync.json()["cursor"]},
                )
            ).status_code == 400
