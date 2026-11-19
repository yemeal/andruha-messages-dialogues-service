from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MessagingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MESSAGING_", env_file=".env", extra="ignore", frozen=True
    )

    enabled: bool = Field(default=False)
    cassandra_config: Path = Field(default=Path("cqltrack.yml"))
    identity_url: str = Field(default="http://identity-service:8001")
    identity_service_token: SecretStr = Field(default=SecretStr(""))
    cursor_key_file: Path | None = Field(default=None)
    repair_interval_seconds: float = Field(default=1, gt=0, le=60)
