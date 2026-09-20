from datetime import UTC, datetime

from app.domain.clock import utc_now


def test_utc_now_returns_timezone_aware_utc_datetime() -> None:
    before = datetime.now(UTC)
    now = utc_now()
    after = datetime.now(UTC)

    assert isinstance(now, datetime)
    assert now.tzinfo is UTC
    assert before <= now <= after
