from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid7

import pytest
from pydantic import Field, ValidationError

from app.domain.base import (
    DomainModel,
    MutableEntity,
    VersionedMutableEntity,
)
from app.domain.exceptions.base import InvalidDomainTimestampError


class DummyMutable(MutableEntity):
    name: Annotated[str, Field(default="initial")]


class DummyVersioned(VersionedMutableEntity):
    name: Annotated[str, Field(default="initial")]
    count: Annotated[int, Field(default=0, ge=0)]


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def entity_id() -> UUID:
    return uuid7()


def test_mutable_entity_initial_state(entity_id: UUID, now: datetime) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)
    assert entity.id == entity_id
    assert entity.created_at == now
    assert entity.updated_at is None


def test_mutable_entity_mark_updated(entity_id: UUID, now: datetime) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)
    later = now + timedelta(minutes=5)
    entity._mark_updated(later)

    assert entity.updated_at == later
    assert entity.created_at == now


def test_mutable_entity_apply_changes_advances_state(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)
    later = now + timedelta(seconds=30)

    changed = entity._apply_changes(now=later, name="updated_name")

    assert changed is True
    assert entity.name == "updated_name"
    assert entity.updated_at == later


def test_mutable_entity_apply_changes_noop_returns_false(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)
    before = entity.model_dump()
    later = now + timedelta(seconds=30)

    changed = entity._apply_changes(now=later, name="initial")

    assert changed is False
    assert entity.updated_at is None
    assert entity.model_dump() == before


def test_mutable_entity_normalizes_updated_at_to_utc(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)
    later_east = (now + timedelta(hours=1)).astimezone(timezone(timedelta(hours=3)))

    entity._mark_updated(later_east)

    assert entity.updated_at == now + timedelta(hours=1)
    assert entity.updated_at.tzinfo is UTC


def test_mutable_entity_rejects_naive_updated_at(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)

    with pytest.raises(InvalidDomainTimestampError):
        entity._mark_updated(datetime(2026, 9, 20, 13, 0, 0))


def test_mutable_entity_rejects_updated_at_preceding_created_at(
    entity_id: UUID, now: datetime
) -> None:
    earlier = now - timedelta(seconds=1)

    with pytest.raises(InvalidDomainTimestampError):
        DummyMutable(id=entity_id, created_at=now, updated_at=earlier)


def test_mutable_entity_allows_updated_at_equal_to_created_at(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyMutable(id=entity_id, created_at=now, updated_at=now)
    assert entity.updated_at == entity.created_at


def test_mutable_entity_rejects_mark_updated_rollback(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyMutable(
        id=entity_id, created_at=now, updated_at=now + timedelta(minutes=10)
    )
    earlier_than_updated = now + timedelta(minutes=5)

    with pytest.raises(InvalidDomainTimestampError):
        entity._mark_updated(earlier_than_updated)


def test_mutable_entity_fields_are_frozen(entity_id: UUID, now: datetime) -> None:
    entity = DummyMutable(id=entity_id, created_at=now)
    before = entity.model_dump()

    with pytest.raises(ValidationError) as exc_info:
        entity.name = "new_name"
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"

    with pytest.raises(ValidationError) as exc_info:
        entity.updated_at = now
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"

    assert entity.model_dump() == before


def test_versioned_mutable_entity_initial_version(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(id=entity_id, created_at=now)
    assert entity.version == 1
    assert entity.updated_at is None


def test_versioned_mutable_entity_apply_changes_advances_state_and_version(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(id=entity_id, created_at=now)
    later = now + timedelta(seconds=30)

    changed = entity._apply_changes(now=later, name="updated_name", count=5)

    assert changed is True
    assert entity.version == 2
    assert entity.name == "updated_name"
    assert entity.count == 5
    assert entity.updated_at == later


def test_versioned_mutable_entity_apply_changes_noop_returns_false(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(id=entity_id, created_at=now)
    before = entity.model_dump()
    later = now + timedelta(seconds=30)

    changed = entity._apply_changes(now=later, name="initial", count=0)

    assert changed is False
    assert entity.version == 1
    assert entity.updated_at is None
    assert entity.model_dump() == before


def test_versioned_mutable_entity_atomic_rollback_on_failed_validation(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(id=entity_id, created_at=now)
    before = entity.model_dump()
    later = now + timedelta(seconds=30)

    with pytest.raises(ValidationError):
        entity._apply_changes(now=later, count=-1)

    assert entity.model_dump() == before
    assert entity.version == 1


def test_versioned_mutable_entity_atomic_rollback_on_invalid_timestamp(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(id=entity_id, created_at=now)
    before = entity.model_dump()
    earlier = now - timedelta(seconds=10)

    with pytest.raises(InvalidDomainTimestampError):
        entity._apply_changes(now=earlier, name="new_name")

    assert entity.model_dump() == before
    assert entity.version == 1


def test_versioned_mutable_entity_direct_mark_updated(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(id=entity_id, created_at=now)
    later = now + timedelta(seconds=10)

    entity._mark_updated(later)

    assert entity.version == 2
    assert entity.updated_at == later


def test_versioned_mutable_entity_mark_updated_rejects_rollback(
    entity_id: UUID, now: datetime
) -> None:
    entity = DummyVersioned(
        id=entity_id, created_at=now, updated_at=now + timedelta(minutes=10)
    )
    earlier = now + timedelta(minutes=5)

    with pytest.raises(InvalidDomainTimestampError):
        entity._mark_updated(earlier)


def test_domain_model_config_extra_forbid() -> None:
    class SampleModel(DomainModel):
        val: int

    with pytest.raises(ValidationError) as exc_info:
        SampleModel.model_validate({"val": 1, "extra_field": "disallowed"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_domain_model_config_preserves_whitespace() -> None:
    class SampleText(DomainModel):
        text: str

    model = SampleText(text="   leading and trailing   \n")
    assert model.text == "   leading and trailing   \n"


def test_domain_model_config_ser_json_bytes() -> None:
    class SampleBytes(DomainModel):
        payload: bytes

    model = SampleBytes(payload=b"test bytes")
    dumped = model.model_dump(mode="json")
    assert dumped["payload"] == "dGVzdCBieXRlcw=="


def test_domain_model_config_arbitrary_types_disallowed() -> None:
    class CustomObject:
        pass

    with pytest.raises(RuntimeError):
        # Pydantic raises RuntimeError during class definition if arbitrary_types_allowed=False
        class InvalidModel(DomainModel):
            obj: CustomObject
