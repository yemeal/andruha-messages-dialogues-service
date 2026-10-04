import pytest

from app.core.settings import Settings


def test_settings_rejects_port_outside_tcp_range() -> None:
    with pytest.raises(ValueError):
        Settings(
            SERVICE_NAME="test-service",
            APP_VERSION="1.0.0",
            APP_ENVIRONMENT="test",
            HOST="127.0.0.1",
            PORT=65536,
            DEV_LOGS=True,
            LOG_LEVEL="INFO",
            MUTE_LOGGERS=(),
        )
