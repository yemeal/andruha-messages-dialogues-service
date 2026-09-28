import pytest
from pydantic import ValidationError

from app.domain.exceptions.groups import InvalidGroupTitleError
from app.domain.value_objects.group_title import GroupTitle


def test_create_valid_group_title() -> None:
    title = GroupTitle.from_str("Backend Team")
    assert title.value == "Backend Team"
    assert str(title) == "Backend Team"
    assert len(title) == 12
    assert repr(title) == "GroupTitle('Backend Team')"


def test_normalization_nfc_and_strip() -> None:
    decomposed = "e\u0301"  # NFD
    raw = f"   Team {decomposed}   "
    title = GroupTitle.from_str(raw)
    assert title.value == "Team \u00e9"


def test_rejects_empty_and_whitespace_only() -> None:
    with pytest.raises(InvalidGroupTitleError):
        GroupTitle.from_str("")

    with pytest.raises(InvalidGroupTitleError):
        GroupTitle.from_str("   \n\t  ")

    with pytest.raises(InvalidGroupTitleError):
        GroupTitle(value="")  # type: ignore[arg-type]


def test_rejects_non_string_value() -> None:
    with pytest.raises(InvalidGroupTitleError):
        GroupTitle(value=123)  # type: ignore[arg-type]


def test_boundary_lengths() -> None:
    t1 = GroupTitle.from_str("A")
    assert len(t1) == 1

    t128 = GroupTitle.from_str("A" * 128)
    assert len(t128) == 128

    with pytest.raises(InvalidGroupTitleError):
        GroupTitle.from_str("A" * 129)


def test_equality_and_hashing() -> None:
    t1 = GroupTitle.from_str("Team")
    t2 = GroupTitle(value="Team")
    t3 = GroupTitle.from_str("Other")

    assert t1 == t2
    assert t1 != t3
    assert t1 != "Team"
    assert hash(t1) == hash(t2)
    assert len({t1, t2, t3}) == 2


def test_immutability() -> None:
    title = GroupTitle.from_str("Original")
    with pytest.raises(ValidationError):
        title.value = "New"  # type: ignore[misc]
