from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from app.domain import MessagePosition
from app.domain.exceptions import DomainError


def test_position_holds_positive_integer(dialog_id: UUID) -> None:
    pos = MessagePosition(dialog_id=dialog_id, value=42)
    assert pos.dialog_id == dialog_id
    assert pos.value == 42
    assert int(pos) == 42


@pytest.mark.parametrize("invalid_value", [0, -1, -100])
def test_position_must_be_strictly_positive(
    invalid_value: int, dialog_id: UUID
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        MessagePosition(dialog_id=dialog_id, value=invalid_value)
    assert exc_info.value.errors()[0]["type"] == "greater_than"


def test_position_ordering_and_equality(dialog_id: UUID) -> None:
    pos1 = MessagePosition(dialog_id=dialog_id, value=10)
    pos2 = MessagePosition(dialog_id=dialog_id, value=20)
    pos1_copy = MessagePosition(dialog_id=dialog_id, value=10)

    assert pos1 < pos2
    assert pos1 <= pos2
    assert pos2 > pos1
    assert pos2 >= pos1
    assert pos1 == pos1_copy
    assert not (pos1 > pos2)
    assert pos1 != pos2
    assert len({pos1, pos1_copy}) == 1


def test_position_comparison_with_incompatible_type_raises_type_error(
    dialog_id: UUID,
) -> None:
    pos = MessagePosition(dialog_id=dialog_id, value=10)
    with pytest.raises(TypeError):
        _ = pos < 10
    with pytest.raises(TypeError):
        _ = pos <= "10"


def test_position_is_frozen(dialog_id: UUID) -> None:
    pos = MessagePosition(dialog_id=dialog_id, value=10)
    with pytest.raises(ValidationError) as exc_info:
        pos.value = 20
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"


def test_positions_from_different_dialogs_cannot_be_ordered() -> None:
    first = MessagePosition(dialog_id=uuid7(), value=10)
    second = MessagePosition(dialog_id=uuid7(), value=20)

    with pytest.raises(DomainError):
        _ = first < second
