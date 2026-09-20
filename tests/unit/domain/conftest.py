from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain import DirectParticipants


@pytest.fixture
def alice_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def bob_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def outsider_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000003")


@pytest.fixture
def participants(alice_id: UUID, bob_id: UUID) -> DirectParticipants:
    return DirectParticipants.from_user_ids(alice_id, bob_id)


@pytest.fixture
def dialog_id() -> UUID:
    return UUID("01995140-0000-7000-8000-000000000001")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 19, 5, 30, tzinfo=UTC)
