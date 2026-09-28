import unicodedata

import pytest
from pydantic import ValidationError

from app.domain.exceptions.messages import InvalidMessageTextError
from app.domain.value_objects.message_text import MessageText


def test_create_valid_message_text() -> None:
    text = MessageText.from_str("Hello world")
    assert text.value == "Hello world"
    assert str(text) == "Hello world"
    assert len(text) == 11
    assert repr(text) == "MessageText('Hello world')"


def test_unicode_nfc_normalization() -> None:
    # Decomposed form NFD: "e" + combining acute accent
    decomposed = "e\u0301"
    # Precomposed form NFC: "é"
    composed = "\u00e9"
    assert decomposed != composed

    text = MessageText.from_str(decomposed)
    assert text.value == composed
    assert unicodedata.is_normalized("NFC", text.value)


def test_newline_normalization() -> None:
    raw = "line1\r\nline2\rline3\nline4"
    text = MessageText.from_str(raw)
    assert text.value == "line1\nline2\nline3\nline4"


def test_strip_whitespace_at_beginning_and_end_while_preserving_inner_formatting() -> (
    None
):
    raw = "   \nline 1\n    line 2 (indented)\nline 3   \n   "
    text = MessageText.from_str(raw)
    expected = "line 1\n    line 2 (indented)\nline 3"
    assert text.value == expected


def test_rejects_empty_and_whitespace_only_messages() -> None:
    with pytest.raises(InvalidMessageTextError):
        MessageText.from_str("")

    with pytest.raises(InvalidMessageTextError):
        MessageText.from_str("   ")

    with pytest.raises(InvalidMessageTextError):
        MessageText.from_str(" \r\n \t \n ")

    with pytest.raises(InvalidMessageTextError):
        MessageText(value="")  # type: ignore[arg-type]


def test_boundary_lengths() -> None:
    single_char = MessageText.from_str("a")
    assert len(single_char) == 1

    max_len_text = "a" * 4096
    text_4096 = MessageText.from_str(max_len_text)
    assert len(text_4096) == 4096

    too_long = "a" * 4097
    with pytest.raises(InvalidMessageTextError):
        MessageText.from_str(too_long)


def test_equality_and_hashing() -> None:
    t1 = MessageText.from_str("Text")
    t2 = MessageText(value="Text")
    t3 = MessageText.from_str("Other")

    assert t1 == t2
    assert t1 != t3
    assert t1 != "Text"
    assert hash(t1) == hash(t2)
    assert len({t1, t2, t3}) == 2


def test_immutability() -> None:
    text = MessageText.from_str("Constant")
    with pytest.raises(ValidationError):
        text.value = "Modified"  # type: ignore[misc]


def test_rejects_non_string_value() -> None:
    with pytest.raises(InvalidMessageTextError):
        MessageText(value=12345)  # type: ignore[arg-type]
