import pytest
from pydantic import ValidationError

from app.domain.exceptions.messages import InvalidMessageTextError
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_text import MessageText


def test_create_content_from_string() -> None:
    content = MessageContent.from_text("Test content")
    assert isinstance(content.text, MessageText)
    assert content.text.value == "Test content"
    assert content.text_value == "Test content"


def test_create_content_from_message_text() -> None:
    text = MessageText.from_str("Preconstructed text")
    content = MessageContent.from_text(text)
    assert content.text == text
    assert content.text_value == "Preconstructed text"


def test_content_rejects_invalid_text() -> None:
    with pytest.raises(InvalidMessageTextError):
        MessageContent.from_text("")

    with pytest.raises(InvalidMessageTextError):
        MessageContent.from_text("   ")


def test_equality_and_hashing() -> None:
    c1 = MessageContent.from_text("Same")
    c2 = MessageContent.from_text("Same")
    c3 = MessageContent.from_text("Different")

    assert c1 == c2
    assert c1 != c3
    assert c1 != "Same"
    assert hash(c1) == hash(c2)
    assert len({c1, c2, c3}) == 2


def test_immutability() -> None:
    content = MessageContent.from_text("Immutable")
    with pytest.raises(ValidationError):
        content.text = MessageText.from_str("New")  # type: ignore[misc]


def test_direct_initialization_with_str() -> None:
    content = MessageContent(text="Direct str")  # type: ignore[arg-type]
    assert content.text_value == "Direct str"


def test_rejects_invalid_type_for_text() -> None:
    with pytest.raises(ValidationError):
        MessageContent(text=12345)  # type: ignore[arg-type]
