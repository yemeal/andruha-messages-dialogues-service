import pytest
from pydantic import ValidationError

from app.domain import MessagePosition


def test_position_holds_positive_integer() -> None:
    pos = MessagePosition(value=42)
    assert pos.value == 42
    assert int(pos) == 42


@pytest.mark.parametrize("invalid_value", [0, -1, -100])
def test_position_must_be_strictly_positive(invalid_value: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        MessagePosition(value=invalid_value)
    assert exc_info.value.errors()[0]["type"] == "greater_than"


def test_position_ordering_and_equality() -> None:
    pos1 = MessagePosition(value=10)
    pos2 = MessagePosition(value=20)
    pos1_copy = MessagePosition(value=10)

    assert pos1 < pos2
    assert pos1 <= pos2
    assert pos2 > pos1
    assert pos2 >= pos1
    assert pos1 == pos1_copy
    assert not (pos1 > pos2)
    assert pos1 != pos2
    assert len({pos1, pos1_copy}) == 1


def test_position_comparison_with_incompatible_type_raises_type_error() -> None:
    pos = MessagePosition(value=10)
    with pytest.raises(TypeError):
        _ = pos < 10
    with pytest.raises(TypeError):
        _ = pos <= "10"


def test_position_is_frozen() -> None:
    pos = MessagePosition(value=10)
    with pytest.raises(ValidationError) as exc_info:
        pos.value = 20
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"
