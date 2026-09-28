from uuid import uuid7

import pytest

from app.domain import MessageContent
from app.domain.exceptions.messages import (
    EmptyMessageContentError,
    InvalidMessageAttachmentsError,
)


def test_attachment_only_content_accepts_object_id_without_metadata() -> None:
    object_id = uuid7()

    content = MessageContent.from_parts(attachments=(object_id,))

    assert content.text is None
    assert content.text_value is None
    assert tuple(reference.value for reference in content.attachments) == (object_id,)
    assert MessageContent.model_validate_json(content.model_dump_json()) == content


def test_content_rejects_duplicate_attachment_ids() -> None:
    attachment = uuid7()

    with pytest.raises(InvalidMessageAttachmentsError):
        MessageContent.from_parts(attachments=(attachment, attachment))


def test_content_rejects_more_than_four_attachments() -> None:
    with pytest.raises(InvalidMessageAttachmentsError):
        MessageContent.from_parts(attachments=tuple(uuid7() for _ in range(5)))


def test_empty_text_with_attachments_becomes_absent_and_order_is_preserved() -> None:
    first = uuid7()
    second = uuid7()

    content = MessageContent.from_parts(text="", attachments=(first, second))

    assert content.text is None
    assert tuple(reference.value for reference in content.attachments) == (
        first,
        second,
    )
    assert MessageContent.model_validate_json(content.model_dump_json()) == content


def test_whitespace_text_with_attachments_becomes_absent() -> None:
    attachment = uuid7()

    content = MessageContent.from_parts(text="  \r\n  ", attachments=(attachment,))

    assert content.text is None
    assert tuple(reference.value for reference in content.attachments) == (attachment,)


def test_content_rejects_no_text_and_no_attachments() -> None:
    with pytest.raises(EmptyMessageContentError):
        MessageContent.from_parts()


def test_content_rejects_whitespace_text_without_attachments() -> None:
    with pytest.raises(EmptyMessageContentError):
        MessageContent.from_parts(text=" \r\n ")
