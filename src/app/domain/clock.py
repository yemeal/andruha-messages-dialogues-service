from datetime import UTC, datetime

from app.domain.exceptions.base import InvalidDomainTimestampError


def utc_now() -> datetime:
    """
    Возвращает текущее время в таймзоне UTC.
    """
    return datetime.now(UTC)


def ensure_utc(dt: datetime | None = None) -> datetime:
    """
    Приводит переданное время к UTC либо возвращает текущее время (utc_now).
    Если передан naive datetime (без таймзоны), поднимает InvalidDomainTimestampError.
    """
    if dt is None:
        return utc_now()
    if dt.utcoffset() is None:
        raise InvalidDomainTimestampError()
    return dt.astimezone(UTC)
