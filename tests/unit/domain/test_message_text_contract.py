from app.domain import MessageText


def test_message_text_removes_surrounding_spaces_and_newlines() -> None:
    text = MessageText.from_str("  hello  \r\n")

    assert text.value == "hello"
