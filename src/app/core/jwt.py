"""Trusted Identity key-ring configuration; reload by rebuilding the verifier."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
KeyId = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S+$")]


class JWTSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JWT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    public_keys: dict[KeyId, Path] = Field(default_factory=dict, max_length=16)
    issuer: NonBlank = Field(default="andruha-identity-service")
    audience: NonBlank = Field(default="andruha-messages-dialogues-service")
    clock_skew_seconds: int = Field(default=30, ge=0, le=300)
