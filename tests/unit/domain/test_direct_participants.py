import json
from collections.abc import Callable
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain import DirectParticipants
from app.domain.exceptions import NotDialogParticipantError, SelfDialogNotAllowedError


@pytest.fixture(params=["factory", "constructor", "mapping", "json"], ids=str)
def pair_factory(
    request: pytest.FixtureRequest,
) -> Callable[[UUID, UUID], DirectParticipants]:
    match request.param:
        case "factory":
            return DirectParticipants.from_user_ids
        case "constructor":
            return lambda first, second: DirectParticipants(first=first, second=second)
        case "mapping":
            return lambda first, second: DirectParticipants.model_validate(
                {"first": first, "second": second}
            )
        case "json":
            return lambda first, second: DirectParticipants.model_validate_json(
                json.dumps({"first": str(first), "second": str(second)})
            )
        case _:
            raise AssertionError(f"Unknown construction path: {request.param}")


@pytest.mark.parametrize("reverse", [False, True], ids=["alice-bob", "bob-alice"])
def test_pair_identity_is_independent_of_initiator(
    pair_factory: Callable[[UUID, UUID], DirectParticipants],
    alice_id: UUID,
    bob_id: UUID,
    reverse: bool,
) -> None:
    first, second = (bob_id, alice_id) if reverse else (alice_id, bob_id)

    pair = pair_factory(first, second)
    same_pair = DirectParticipants.from_user_ids(alice_id, bob_id)

    assert (pair.first, pair.second) == (alice_id, bob_id)
    assert pair == same_pair
    assert len({pair, same_pair}) == 1


def test_self_dialog_is_rejected_on_every_construction_path(
    pair_factory: Callable[[UUID, UUID], DirectParticipants], alice_id: UUID
) -> None:
    with pytest.raises(SelfDialogNotAllowedError):
        pair_factory(alice_id, alice_id)


@pytest.mark.parametrize(
    ("user_fixture", "expected"),
    [
        pytest.param("alice_id", True, id="first-participant"),
        pytest.param("bob_id", True, id="second-participant"),
        pytest.param("outsider_id", False, id="outsider"),
    ],
)
def test_only_users_in_the_pair_are_participants(
    participants: DirectParticipants,
    request: pytest.FixtureRequest,
    user_fixture: str,
    expected: bool,
) -> None:
    user_id = request.getfixturevalue(user_fixture)
    assert (user_id in participants) is expected


@pytest.mark.parametrize("reverse", [False, True], ids=["alice", "bob"])
def test_participant_gets_the_other_user_as_peer(
    participants: DirectParticipants, alice_id: UUID, bob_id: UUID, reverse: bool
) -> None:
    actor, peer = (bob_id, alice_id) if reverse else (alice_id, bob_id)

    assert participants.peer_of(actor) == peer


def test_outsider_cannot_obtain_a_peer(
    participants: DirectParticipants, outsider_id: UUID
) -> None:
    with pytest.raises(NotDialogParticipantError):
        participants.peer_of(outsider_id)


def test_pairs_with_different_users_are_distinct(
    participants: DirectParticipants, alice_id: UUID, outsider_id: UUID
) -> None:
    other_pair = DirectParticipants.from_user_ids(alice_id, outsider_id)

    assert participants != other_pair
    assert len({participants, other_pair}) == 2


def test_participants_helper_properties(
    participants: DirectParticipants, alice_id: UUID, bob_id: UUID
) -> None:
    assert participants.as_tuple == (alice_id, bob_id)
    assert participants.as_set == frozenset({alice_id, bob_id})
    assert list(participants.as_tuple) == [alice_id, bob_id]


@pytest.mark.parametrize("field", ["first", "second"])
@pytest.mark.parametrize("operation", ["assign", "delete"])
def test_pair_cannot_change_after_creation(
    participants: DirectParticipants, outsider_id: UUID, field: str, operation: str
) -> None:
    before = participants.model_dump()
    pair_hash = hash(participants)

    with pytest.raises(ValidationError) as exc_info:
        if operation == "assign":
            setattr(participants, field, outsider_id)
        else:
            delattr(participants, field)

    assert exc_info.value.errors()[0]["type"] == "frozen_instance"
    assert participants.model_dump() == before
    assert hash(participants) == pair_hash


@pytest.mark.parametrize("field", ["first", "second"])
@pytest.mark.parametrize(
    "invalid_id", [None, "not-a-uuid", 7], ids=["null", "malformed", "integer"]
)
def test_restoration_rejects_invalid_user_identity(
    participants: DirectParticipants, field: str, invalid_id: object
) -> None:
    data = {**participants.model_dump(), field: invalid_id}

    with pytest.raises(ValidationError) as exc_info:
        DirectParticipants.model_validate(data)

    assert exc_info.value.errors()[0]["loc"] == (field,)


def test_pair_rejects_an_extra_participant(
    participants: DirectParticipants, outsider_id: UUID
) -> None:
    data = {**participants.model_dump(), "third_user": outsider_id}

    with pytest.raises(ValidationError) as exc_info:
        DirectParticipants.model_validate(data)

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
