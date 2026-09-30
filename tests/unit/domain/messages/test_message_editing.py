from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain import (
    ClientMessageId,
    Message,
    MessageContent,
    MessagePosition,
    MessageText,
)
from app.domain.exceptions import (
    DomainError,
    EmptyMessageContentError,
    InvalidDomainTimestampError,
    InvalidMessageEditMetadataError,
    InvalidMessageTextError,
    NotMessageAuthorError,
)


@pytest.fixture
def message(alice_id: UUID, dialog_id: UUID, now: datetime) -> Message:
    return Message.create(
        dialog_id=dialog_id,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_str(
            "01995140-0000-7000-8000-000000000009"
        ),
        content=MessageContent.from_text("Original text"),
        position=MessagePosition(dialog_id=dialog_id, value=1),
        message_id=UUID("01995140-0000-7000-8000-000000000010"),
        now=now,
    )


def test_new_message_has_no_edit_marker(message: Message) -> None:
    assert message.version == 1
    assert message.updated_at is None
    assert message.is_edited is False
    assert message.edited_at is None


def test_author_edits_text_without_changing_send_identity(
    message: Message, alice_id: UUID, now: datetime
) -> None:
    original_identity = message.model_dump(exclude={"content", "version", "updated_at"})
    edit_time = now + timedelta(minutes=1)

    changed = message.edit_text(actor_id=alice_id, text="Revised text", now=edit_time)

    assert changed is True
    assert message.text_value == "Revised text"
    assert message.version == 2
    assert message.updated_at == edit_time
    assert message.is_edited is True
    assert message.edited_at == edit_time
    assert (
        message.model_dump(exclude={"content", "version", "updated_at"})
        == original_identity
    )


def test_edited_message_roundtrip_preserves_the_edit_marker(
    message: Message, alice_id: UUID, now: datetime
) -> None:
    edit_time = now + timedelta(minutes=1)
    message.edit_text(actor_id=alice_id, text="Revised text", now=edit_time)

    from_mapping = Message.model_validate(message.model_dump())
    from_json = Message.model_validate_json(message.model_dump_json())

    for restored in (from_mapping, from_json):
        assert restored == message
        assert restored.text_value == "Revised text"
        assert restored.version == 2
        assert restored.is_edited is True
        assert restored.edited_at == edit_time


@pytest.mark.parametrize("text", ["Original text", "Revised text"])
def test_other_user_cannot_edit_even_when_text_is_unchanged(
    message: Message, bob_id: UUID, now: datetime, text: str
) -> None:
    before = message.model_dump()

    with pytest.raises(NotMessageAuthorError):
        message.edit_text(actor_id=bob_id, text=text, now=now + timedelta(minutes=1))

    assert message.model_dump() == before
    assert message.is_edited is False
    assert message.edited_at is None


@pytest.mark.parametrize(
    "text",
    ["Original text", "  Original text\r\n", MessageText.from_str("Original text")],
)
def test_equivalent_text_does_not_mark_new_message_as_edited(
    message: Message, alice_id: UUID, now: datetime, text: str | MessageText
) -> None:
    before = message.model_dump()

    changed = message.edit_text(
        actor_id=alice_id, text=text, now=now + timedelta(minutes=1)
    )

    assert changed is False
    assert message.model_dump() == before
    assert message.version == 1
    assert message.is_edited is False
    assert message.edited_at is None


def test_repeating_an_edit_preserves_its_original_marker(
    message: Message, alice_id: UUID, now: datetime
) -> None:
    edit_time = now + timedelta(minutes=1)
    message.edit_text(actor_id=alice_id, text="Revised text", now=edit_time)
    before = message.model_dump()

    changed = message.edit_text(
        actor_id=alice_id,
        text="  Revised text\r\n",
        now=now + timedelta(hours=1),
    )

    assert changed is False
    assert message.model_dump() == before
    assert message.version == 2
    assert message.is_edited is True
    assert message.edited_at == edit_time


def test_reverting_text_is_another_edit(
    message: Message, alice_id: UUID, now: datetime
) -> None:
    message.edit_text(
        actor_id=alice_id, text="Revised text", now=now + timedelta(minutes=1)
    )
    revert_time = now + timedelta(minutes=2)

    changed = message.edit_text(
        actor_id=alice_id, text="Original text", now=revert_time
    )

    assert changed is True
    assert message.text_value == "Original text"
    assert message.version == 3
    assert message.is_edited is True
    assert message.edited_at == revert_time


def test_multiple_edits_at_creation_time_still_have_an_edit_marker(
    message: Message, alice_id: UUID, now: datetime
) -> None:
    assert message.edit_text(actor_id=alice_id, text="First edit", now=now)
    assert message.edit_text(actor_id=alice_id, text="Second edit", now=now)

    assert message.text_value == "Second edit"
    assert message.version == 3
    assert message.is_edited is True
    assert message.edited_at == message.created_at


def test_unicode_and_newline_equivalent_text_is_not_an_edit(
    message: Message, alice_id: UUID, now: datetime
) -> None:
    unicode_message = message.model_copy(
        update={"content": MessageContent.from_text("Caf\u00e9\nLine two")}
    )
    before = unicode_message.model_dump()

    changed = unicode_message.edit_text(
        actor_id=alice_id,
        text="  Cafe\u0301\r\nLine two\r\n",
        now=now + timedelta(minutes=1),
    )

    assert changed is False
    assert unicode_message.model_dump() == before
    assert unicode_message.is_edited is False
    assert unicode_message.edited_at is None


@pytest.fixture
def message_with_attachments(message: Message) -> Message:
    return message.model_copy(
        update={
            "content": MessageContent.from_parts(
                text="Original text",
                attachments=(
                    UUID("01995140-0000-7000-8000-000000000012"),
                    UUID("01995140-0000-7000-8000-000000000011"),
                ),
            )
        }
    )


def test_text_edit_preserves_attachment_ids_and_order(
    message_with_attachments: Message, alice_id: UUID, now: datetime
) -> None:
    changed = message_with_attachments.edit_text(
        actor_id=alice_id,
        text="New caption",
        now=now + timedelta(minutes=1),
    )

    assert changed is True
    assert message_with_attachments.text_value == "New caption"
    assert tuple(
        reference.value for reference in message_with_attachments.content.attachments
    ) == (
        UUID("01995140-0000-7000-8000-000000000012"),
        UUID("01995140-0000-7000-8000-000000000011"),
    )


@pytest.mark.parametrize("text", [None, "", "  \r\n  "])
def test_author_can_remove_caption_without_removing_attachments(
    message_with_attachments: Message,
    alice_id: UUID,
    now: datetime,
    text: str | None,
) -> None:
    attachments = message_with_attachments.content.attachments
    edit_time = now + timedelta(minutes=1)

    changed = message_with_attachments.edit_text(
        actor_id=alice_id, text=text, now=edit_time
    )

    assert changed is True
    assert message_with_attachments.text_value is None
    assert message_with_attachments.content.attachments == attachments
    assert message_with_attachments.version == 2
    assert message_with_attachments.is_edited is True
    assert message_with_attachments.edited_at == edit_time


@pytest.mark.parametrize(
    ("text", "error"),
    [
        pytest.param("x" * 4097, InvalidMessageTextError, id="over-limit"),
        pytest.param("", EmptyMessageContentError, id="empty"),
        pytest.param("  \r\n  ", EmptyMessageContentError, id="whitespace"),
        pytest.param(None, EmptyMessageContentError, id="no-text"),
    ],
)
def test_invalid_text_leaves_message_and_edit_marker_unchanged(
    message: Message,
    alice_id: UUID,
    now: datetime,
    text: str | None,
    error: type[DomainError],
) -> None:
    before = message.model_dump()

    with pytest.raises(error):
        message.edit_text(actor_id=alice_id, text=text, now=now + timedelta(minutes=1))

    assert message.model_dump() == before
    assert message.version == 1
    assert message.is_edited is False
    assert message.edited_at is None


@pytest.mark.parametrize(
    "edit_time",
    [
        pytest.param(datetime(2026, 9, 19, 5, 32), id="naive"),
        pytest.param(datetime(2026, 9, 19, 5, 29, tzinfo=UTC), id="before-creation"),
        pytest.param(
            datetime(2026, 9, 19, 5, 30, 30, tzinfo=UTC), id="before-last-edit"
        ),
    ],
)
def test_invalid_edit_time_preserves_previous_text_version_and_marker(
    message: Message, alice_id: UUID, now: datetime, edit_time: datetime
) -> None:
    first_edit_time = now + timedelta(minutes=1)
    message.edit_text(actor_id=alice_id, text="First edit", now=first_edit_time)
    before = message.model_dump()

    with pytest.raises(InvalidDomainTimestampError):
        message.edit_text(actor_id=alice_id, text="Second edit", now=edit_time)

    assert message.model_dump() == before
    assert message.text_value == "First edit"
    assert message.version == 2
    assert message.is_edited is True
    assert message.edited_at == first_edit_time


def test_legacy_snapshot_restores_as_a_message_without_edits(
    message: Message,
) -> None:
    snapshot = message.model_dump(mode="json")
    snapshot.pop("version")
    snapshot.pop("updated_at")

    restored = Message.model_validate(snapshot)

    assert restored == message
    assert restored.version == 1
    assert restored.is_edited is False
    assert restored.edited_at is None


@pytest.mark.parametrize(
    ("version", "updated_at"),
    [
        pytest.param(
            1, datetime(2026, 9, 19, 5, 31, tzinfo=UTC), id="unmodified-with-edit-time"
        ),
        pytest.param(2, None, id="edited-without-edit-time"),
    ],
)
def test_restore_rejects_inconsistent_edit_metadata(
    message: Message, version: int, updated_at: datetime | None
) -> None:
    snapshot = {
        **message.model_dump(),
        "version": version,
        "updated_at": updated_at,
    }

    with pytest.raises(InvalidMessageEditMetadataError):
        Message.model_validate(snapshot)
