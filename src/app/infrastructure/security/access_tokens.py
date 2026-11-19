"""Verify Identity access tokens with a preloaded immutable RSA public-key ring."""

from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.jwt import JWTSettings

MAX_ACCESS_TOKEN_LENGTH = 8192
NumericDate = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class InvalidAccessTokenError(Exception):
    """The token does not establish a trusted Identity principal."""


class AccessTokenClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    sub: UUID
    jti: UUID
    role: Literal["USER", "ADMIN"]
    iat: NumericDate
    exp: NumericDate

    @model_validator(mode="after")
    def validate_lifetime(self) -> Self:
        if self.exp <= self.iat:
            raise ValueError("Token expiry must follow issuance")
        return self


class AccessTokenVerifier:
    def __init__(self, settings: JWTSettings) -> None:
        keys: dict[str, RSAPublicKey] = {}
        for key_id, path in settings.public_keys.items():
            key = serialization.load_pem_public_key(path.read_bytes())
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError(
                    "Access verification requires RSA public keys >= 2048 bits"
                )
            keys[key_id] = key
        if not keys:
            raise ValueError("Access verification requires a trusted public key")
        self._keys = MappingProxyType(keys)
        self._issuer = settings.issuer
        self._audience = settings.audience
        self._leeway = settings.clock_skew_seconds

    def verify(self, token: str) -> UUID:
        try:
            if not token or len(token) > MAX_ACCESS_TOKEN_LENGTH:
                raise InvalidAccessTokenError()
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "at+jwt"
                or header.get("crit")
            ):
                raise InvalidAccessTokenError()
            key_id = header.get("kid")
            if not isinstance(key_id, str) or key_id not in self._keys:
                raise InvalidAccessTokenError()
            payload = jwt.decode(
                token,
                self._keys[key_id],
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={"require": ["iss", "sub", "aud", "iat", "exp", "jti", "role"]},
            )
            return AccessTokenClaims.model_validate(payload).sub
        except (jwt.PyJWTError, TypeError, ValueError, OverflowError) as error:
            raise InvalidAccessTokenError() from error
