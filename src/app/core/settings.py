"""Environment-backed bootstrap settings."""

import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_SERVICE_NAME = "andruha-messages-dialogues-service"
DEFAULT_APP_VERSION = "0.1.0"
DEFAULT_APP_ENVIRONMENT = "development"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8003
DEFAULT_DEV_LOGS = True
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MUTE_LOGGERS: tuple[str, ...] = ()
MIN_PORT = 1
MAX_PORT = 65535


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _read_port(default: int) -> int:
    port = int(os.getenv("PORT", str(default)))
    if not MIN_PORT <= port <= MAX_PORT:
        raise ValueError(f"PORT must be between {MIN_PORT} and {MAX_PORT}")
    return port


def _read_mute_loggers() -> tuple[str, ...]:
    raw_value = os.getenv("MUTE_LOGGERS", ",".join(DEFAULT_MUTE_LOGGERS))
    return tuple(
        logger_name.strip()
        for logger_name in raw_value.split(",")
        if logger_name.strip()
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
        frozen=True,
    )

    SERVICE_NAME: str = DEFAULT_SERVICE_NAME
    APP_VERSION: str = DEFAULT_APP_VERSION
    APP_ENVIRONMENT: str = DEFAULT_APP_ENVIRONMENT
    HOST: str = DEFAULT_HOST
    PORT: int = Field(default=DEFAULT_PORT, ge=MIN_PORT, le=MAX_PORT)
    DEV_LOGS: bool = DEFAULT_DEV_LOGS
    LOG_LEVEL: str = DEFAULT_LOG_LEVEL
    MUTE_LOGGERS: Annotated[tuple[str, ...], NoDecode] = DEFAULT_MUTE_LOGGERS

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("MUTE_LOGGERS", mode="before")
    @classmethod
    def parse_mute_loggers(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(
                logger_name.strip()
                for logger_name in value.split(",")
                if logger_name.strip()
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
