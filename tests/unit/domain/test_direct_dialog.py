import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain import DirectDialog, DirectParticipants
from app.domain.clock import utc_now
from app.domain.exceptions import (
    InvalidDomainTimestampError,
    NotDialogParticipantError,
    SelfDialogNotAllowedError,
)


@pytest.fixture
def dialog(
    dialog_id: UUID, participants: DirectParticipants, now: datetime
) -> DirectDialog:
    return DirectDialog.create(dialog_id=dialog_id, participants=participants, now=now)


@pytest.fixture(params=["factory", "constructor", "mapping", "json"], ids=str)
def dialog_factory(
    request: pytest.FixtureRequest, dialog_id: UUID, participants: DirectParticipants
) -> Callable[[datetime], DirectDialog]:
    match request.param:
        case "factory":
            return lambda instant: DirectDialog.create(
                dialog_id=dialog_id, participants=participants, now=instant
            )
        case "constructor":
            return lambda instant: DirectDialog(
                id=dialog_id, participants=participants, created_at=instant
            )
        case "mapping":
            return lambda instant: DirectDialog.model_validate(
                {
                    "id": dialog_id,
                    "participants": participants.model_dump(),
                    "created_at": instant,
                }
            )
        case "json":
            return lambda instant: DirectDialog.model_validate_json(
                json.dumps(
                    {
                        "id": str(dialog_id),
                        "participants": participants.model_dump(mode="json"),
                        "created_at": instant.isoformat(),
                    }
                )
            )
        case _:
            raise AssertionError(f"Unknown construction path: {request.param}")


def test_dialog_preserves_supplied_identity_participants_and_creation_time(
    dialog_id: UUID, participants: DirectParticipants, now: datetime
) -> None:
    dialog = DirectDialog.create(
        dialog_id=dialog_id, participants=participants, now=now
    )

    assert dialog.id == dialog_id
    assert dialog.participants == participants
    assert dialog.created_at == now


def test_create_generates_default_uuidv7_identity_and_utc_time(
    participants: DirectParticipants,
) -> None:
    before = utc_now()
    dialog = DirectDialog.create(participants=participants)
    after = utc_now()

    assert isinstance(dialog.id, UUID)
    assert dialog.id.version == 7
    assert dialog.participants == participants
    assert dialog.created_at.tzinfo is UTC
    assert before <= dialog.created_at <= after


def test_create_allows_providing_dialog_id_or_time_independently(
    dialog_id: UUID, participants: DirectParticipants, now: datetime
) -> None:
    dialog_with_id = DirectDialog.create(dialog_id=dialog_id, participants=participants)
    assert dialog_with_id.id == dialog_id
    assert dialog_with_id.participants == participants
    assert dialog_with_id.created_at.tzinfo is UTC

    dialog_with_time = DirectDialog.create(participants=participants, now=now)
    assert isinstance(dialog_with_time.id, UUID)
    assert dialog_with_time.id.version == 7
    assert dialog_with_time.participants == participants
    assert dialog_with_time.created_at == now


@pytest.mark.parametrize("offset_hours", [0, 7, -5], ids=["utc", "east", "west"])
def test_creation_and_restoration_normalize_the_same_instant_to_utc(
    dialog_factory: Callable[[datetime], DirectDialog],
    now: datetime,
    offset_hours: int,
) -> None:
    local_time = now.astimezone(timezone(timedelta(hours=offset_hours)))

    dialog = dialog_factory(local_time)

    assert dialog.created_at == now
    assert dialog.created_at.tzinfo is UTC


def test_creation_and_restoration_reject_time_without_a_timezone(
    dialog_factory: Callable[[datetime], DirectDialog], now: datetime
) -> None:
    with pytest.raises(InvalidDomainTimestampError):
        dialog_factory(now.replace(tzinfo=None))


@pytest.mark.parametrize("reverse", [False, True], ids=["alice", "bob"])
def test_each_dialog_participant_can_access_the_dialog_and_resolve_the_peer(
    dialog: DirectDialog, alice_id: UUID, bob_id: UUID, reverse: bool
) -> None:
    actor, peer = (bob_id, alice_id) if reverse else (alice_id, bob_id)

    assert actor in dialog
    assert dialog.peer_of(actor) == peer


def test_dialog_denies_an_outsider(dialog: DirectDialog, outsider_id: UUID) -> None:
    assert outsider_id not in dialog
    with pytest.raises(NotDialogParticipantError):
        dialog.peer_of(outsider_id)


def test_dialog_helper_properties(
    dialog: DirectDialog, alice_id: UUID, bob_id: UUID
) -> None:
    assert dialog.as_tuple == (alice_id, bob_id)
    assert dialog.as_set == frozenset({alice_id, bob_id})
    assert list(dialog.as_tuple) == [alice_id, bob_id]


@pytest.mark.parametrize("format_name", ["mapping", "json"])
def test_restoration_preserves_the_entire_dialog_snapshot(
    dialog: DirectDialog, format_name: str
) -> None:
    if format_name == "mapping":
        restored = DirectDialog.model_validate(dialog.model_dump())
    else:
        restored = DirectDialog.model_validate_json(dialog.model_dump_json())

    assert restored.model_dump() == dialog.model_dump()


def test_restoration_canonicalizes_nested_participants(
    dialog: DirectDialog, alice_id: UUID, bob_id: UUID
) -> None:
    data = {
        **dialog.model_dump(),
        "participants": {"first": bob_id, "second": alice_id},
    }

    restored = DirectDialog.model_validate(data)

    assert restored.model_dump() == dialog.model_dump()


def test_restoration_cannot_bypass_the_self_dialog_rule(
    dialog: DirectDialog, alice_id: UUID
) -> None:
    data = {
        **dialog.model_dump(),
        "participants": {"first": alice_id, "second": alice_id},
    }

    with pytest.raises(SelfDialogNotAllowedError):
        DirectDialog.model_validate(data)


@pytest.mark.parametrize("field", ["id", "created_at", "participants"])
def test_restoration_never_invents_missing_identity_time_or_participants(
    dialog: DirectDialog, field: str
) -> None:
    data = dialog.model_dump()
    del data[field]

    with pytest.raises(ValidationError) as exc_info:
        DirectDialog.model_validate(data)

    assert exc_info.value.errors()[0]["type"] == "missing"
    assert exc_info.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["id", "created_at", "participants"])
@pytest.mark.parametrize("operation", ["assign", "delete"])
def test_dialog_state_cannot_be_replaced_or_deleted(
    dialog: DirectDialog, field: str, operation: str
) -> None:
    before = dialog.model_dump()

    with pytest.raises(ValidationError) as exc_info:
        if operation == "assign":
            setattr(dialog, field, None)
        else:
            delattr(dialog, field)

    assert exc_info.value.errors()[0]["type"] == "frozen_instance"
    assert dialog.model_dump() == before


def test_nested_participant_cannot_be_changed_through_dialog(
    dialog: DirectDialog, outsider_id: UUID
) -> None:
    before = dialog.model_dump()

    with pytest.raises(ValidationError) as exc_info:
        dialog.participants.second = outsider_id

    assert exc_info.value.errors()[0]["type"] == "frozen_instance"
    assert dialog.model_dump() == before


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        pytest.param("id", "not-a-uuid", id="invalid-dialog-id"),
        pytest.param("created_at", "not-a-date", id="invalid-time"),
        pytest.param("participants", None, id="missing-pair"),
    ],
)
def test_restoration_rejects_malformed_dialog_fields(
    dialog: DirectDialog, field: str, invalid_value: object
) -> None:
    data = {**dialog.model_dump(), field: invalid_value}

    with pytest.raises(ValidationError) as exc_info:
        DirectDialog.model_validate(data)

    assert exc_info.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("nested", [False, True], ids=["dialog", "participants"])
def test_restoration_rejects_unknown_state(dialog: DirectDialog, nested: bool) -> None:
    data = dialog.model_dump()
    target = data["participants"] if nested else data
    target["messages"] = []

    with pytest.raises(ValidationError) as exc_info:
        DirectDialog.model_validate(data)

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
