import base64
import json
from datetime import UTC, datetime
from uuid import uuid7

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.jwt import JWTSettings
from app.infrastructure.security.access_tokens import (
    AccessTokenVerifier,
    InvalidAccessTokenError,
)

NOW = datetime(2026, 11, 16, 3, tzinfo=UTC)


@pytest.fixture
def token_material(tmp_path, monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(jwt.api_jwt, "datetime", FrozenDatetime)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_path = tmp_path / "identity-public.pem"
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = JWTSettings(
        public_keys={"identity-v1": public_path},
        issuer="andruha-identity-service",
        audience="andruha-messages-dialogues-service",
        clock_skew_seconds=0,
        _env_file=None,
    )
    return private, settings


def claims():
    return {
        "iss": "andruha-identity-service",
        "sub": str(uuid7()),
        "aud": ["andruha-user-profile-service", "andruha-messages-dialogues-service"],
        "iat": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 900,
        "jti": str(uuid7()),
        "role": "USER",
    }


def test_trusted_identity_access_token_yields_its_subject(token_material):
    private, settings = token_material
    payload = claims()
    encoded = jwt.encode(
        payload,
        private,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v1",
        },
    )

    assert str(AccessTokenVerifier(settings).verify(encoded)) == payload["sub"]


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "untrusted-identity"),
        ("aud", ["andruha-user-profile-service"]),
        ("sub", "not-a-user-id"),
        ("jti", "not-a-token-id"),
        ("role", "ROOT"),
        ("iat", True),
        ("iat", str(int(NOW.timestamp()))),
        ("iat", int(NOW.timestamp()) + 60),
        ("exp", int(NOW.timestamp()) - 1),
        ("exp", str(int(NOW.timestamp()) + 900)),
        ("exp", float("inf")),
    ],
    ids=[
        "issuer",
        "audience",
        "subject",
        "jti",
        "role",
        "boolean-iat",
        "string-iat",
        "future-iat",
        "expired",
        "string-exp",
        "infinite-exp",
    ],
)
def test_invalid_signed_claim_is_rejected(token_material, claim, value):
    private, settings = token_material
    payload = claims() | {claim: value}
    encoded = jwt.encode(
        payload,
        private,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v1",
        },
    )
    with pytest.raises(InvalidAccessTokenError):
        AccessTokenVerifier(settings).verify(encoded)


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "iat", "exp", "jti", "role"])
def test_missing_required_claim_is_rejected(token_material, claim):
    private, settings = token_material
    payload = claims()
    del payload[claim]
    encoded = jwt.encode(
        payload,
        private,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v1",
        },
    )
    with pytest.raises(InvalidAccessTokenError):
        AccessTokenVerifier(settings).verify(encoded)


@pytest.mark.parametrize(
    "header",
    [
        {"typ": "JWT", "kid": "identity-v1"},
        {"typ": "at+jwt"},
        {"typ": "at+jwt", "kid": "untrusted-key"},
        {"typ": "at+jwt", "kid": "identity-v1", "crit": ["unsupported-extension"]},
    ],
)
def test_untrusted_header_is_rejected(token_material, header):
    private, settings = token_material
    encoded = jwt.encode(claims(), private, algorithm="RS256", headers=header)
    with pytest.raises(InvalidAccessTokenError):
        AccessTokenVerifier(settings).verify(encoded)


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_another_algorithm_cannot_select_a_trusted_rsa_key(token_material, algorithm):
    _, settings = token_material
    encoded = jwt.encode(
        claims(),
        None if algorithm == "none" else bytes(64),
        algorithm=algorithm,
        headers={"typ": "at+jwt", "kid": "identity-v1"},
    )
    with pytest.raises(InvalidAccessTokenError):
        AccessTokenVerifier(settings).verify(encoded)


def test_changed_subject_without_identity_signature_is_rejected(token_material):
    private, settings = token_material
    payload = claims()
    encoded = jwt.encode(
        payload,
        private,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v1",
        },
    )
    header, _, signature = encoded.split(".")
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps(payload | {"sub": str(uuid7())}).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(InvalidAccessTokenError):
        AccessTokenVerifier(settings).verify(f"{header}.{forged_payload}.{signature}")


def test_signature_from_an_untrusted_key_is_rejected(token_material):
    _, settings = token_material
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = jwt.encode(
        claims(),
        other,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v1",
        },
    )
    with pytest.raises(InvalidAccessTokenError):
        AccessTokenVerifier(settings).verify(encoded)


def test_key_rotation_keeps_overlap_until_verifier_is_rebuilt(token_material, tmp_path):
    old, settings = token_material
    new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_path = tmp_path / "identity-v2.pem"
    new_path.write_bytes(
        new.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    overlap = JWTSettings(
        public_keys=settings.public_keys | {"identity-v2": new_path},
        issuer=settings.issuer,
        audience=settings.audience,
        clock_skew_seconds=0,
        _env_file=None,
    )
    old_token = jwt.encode(
        claims(),
        old,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v1",
        },
    )
    new_token = jwt.encode(
        claims(),
        new,
        algorithm="RS256",
        headers={
            "typ": "at+jwt",
            "kid": "identity-v2",
        },
    )
    current = AccessTokenVerifier(overlap)
    assert current.verify(old_token)
    assert current.verify(new_token)
    rebuilt = AccessTokenVerifier(
        JWTSettings(
            public_keys={"identity-v2": new_path},
            issuer=settings.issuer,
            audience=settings.audience,
            clock_skew_seconds=0,
            _env_file=None,
        )
    )
    assert rebuilt.verify(new_token)
    with pytest.raises(InvalidAccessTokenError):
        rebuilt.verify(old_token)
    assert current.verify(old_token)
