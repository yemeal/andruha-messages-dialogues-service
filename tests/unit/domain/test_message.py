from datetime import datetime, timedelta
from uuid import uuid7

import pytest
from pydantic import ValidationError

from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.clock import utc_now
from app.domain.exceptions.base import InvalidDomainTimestampError
from app.domain.exceptions.dialogues import NotDialogParticipantError
from app.domain.exceptions.messages import (
    MessageCreatedAtPrecedesDialogError,
    PositionDialogMismatchError,
)
from app.domain.policies.message_posting import MessagePostingPolicy
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition


def _create_dialog(user_a=None, user_b=None, now=None) -> DirectDialog:
    u1 = user_a if user_a is not None else uuid7()
    u2 = user_b if user_b is not None else uuid7()
    participants = DirectParticipants.from_user_ids(u1, u2)
    return DirectDialog.create(participants=participants, now=now)


def _position(dialog: DirectDialog, value: int) -> MessagePosition:
    return MessagePosition(dialog_id=dialog.id, value=value)


def test_create_message_success() -> None:
    t0 = utc_now()
    u1 = uuid7()
    u2 = uuid7()
    dialog = _create_dialog(user_a=u1, user_b=u2, now=t0)

    client_msg_id = ClientMessageId.generate()
    content = MessageContent.from_text("Hello peer")
    pos = _position(dialog, 1)
    msg_id = uuid7()
    msg_time = t0 + timedelta(seconds=1)

    msg = MessagePostingPolicy.create_message(
        message_id=msg_id,
        dialog=dialog,
        sender_id=u1,
        client_message_id=client_msg_id,
        content=content,
        position=pos,
        now=msg_time,
    )

    assert msg.id == msg_id
    assert msg.dialog_id == dialog.id
    assert msg.sender_id == u1
    assert msg.client_message_id == client_msg_id
    assert msg.content == content
    assert msg.position == pos
    assert msg.created_at == msg_time


def test_message_rejects_position_from_another_dialog() -> None:
    dialog = _create_dialog()
    sender_id, _ = dialog.as_tuple

    with pytest.raises(PositionDialogMismatchError):
        MessagePostingPolicy.create_message(
            dialog=dialog,
            sender_id=sender_id,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Wrong position"),
            position=MessagePosition(dialog_id=uuid7(), value=1),
        )


def test_message_reconstitution_rejects_position_from_another_dialog() -> None:
    dialog = _create_dialog()
    sender_id, _ = dialog.as_tuple
    message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=sender_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Stored message"),
        position=_position(dialog, 1),
    )
    snapshot = message.model_dump()
    snapshot["position"]["dialog_id"] = uuid7()

    with pytest.raises(PositionDialogMismatchError):
        Message.model_validate(snapshot)


def test_create_message_defaults_id_and_time() -> None:
    dialog = _create_dialog()
    u1, _ = dialog.as_tuple
    client_msg_id = ClientMessageId.generate()
    content = MessageContent.from_text("Default test")
    pos = _position(dialog, 1)

    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=u1,
        client_message_id=client_msg_id,
        content=content,
        position=pos,
    )

    assert msg.id.version == 7
    assert msg.created_at >= dialog.created_at


def test_create_message_rejects_outsider_sender() -> None:
    dialog = _create_dialog()
    outsider = uuid7()
    client_msg_id = ClientMessageId.generate()
    content = MessageContent.from_text("Hello")
    pos = _position(dialog, 1)

    with pytest.raises(NotDialogParticipantError):
        MessagePostingPolicy.create_message(
            dialog=dialog,
            sender_id=outsider,
            client_message_id=client_msg_id,
            content=content,
            position=pos,
        )


def test_create_message_rejects_naive_timestamp() -> None:
    dialog = _create_dialog()
    u1, _ = dialog.as_tuple
    naive_time = datetime(2026, 9, 23, 12, 0, 0)

    with pytest.raises(InvalidDomainTimestampError):
        MessagePostingPolicy.create_message(
            dialog=dialog,
            sender_id=u1,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Hello"),
            position=_position(dialog, 1),
            now=naive_time,
        )


def test_create_message_rejects_timestamp_before_dialog_creation() -> None:
    t0 = utc_now()
    dialog = _create_dialog(now=t0)
    u1, _ = dialog.as_tuple
    earlier = t0 - timedelta(seconds=10)

    with pytest.raises(MessageCreatedAtPrecedesDialogError):
        MessagePostingPolicy.create_message(
            dialog=dialog,
            sender_id=u1,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Hello"),
            position=_position(dialog, 1),
            now=earlier,
        )


def test_saved_message_has_the_same_identity_and_content_contract() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    dialog = SavedDialog.create(user_id=user_id)
    message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=user_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Self talk"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
    )
    assert message.sender_id == user_id
    assert message.dialog_id == dialog.id
    assert message.text_value == "Self talk"


def test_immutability() -> None:
    dialog = _create_dialog()
    u1, _ = dialog.as_tuple
    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=u1,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Immutable"),
        position=_position(dialog, 1),
    )

    with pytest.raises(ValidationError):
        msg.sender_id = uuid7()  # type: ignore[misc]

    with pytest.raises(ValidationError):
        msg.content = MessageContent.from_text("Other")  # type: ignore[misc]


def test_roundtrip_serialization() -> None:
    dialog = _create_dialog()
    u1, _ = dialog.as_tuple
    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=u1,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Roundtrip"),
        position=_position(dialog, 1),
    )

    data = msg.model_dump()
    reconstituted = Message.model_validate(data)
    assert reconstituted == msg


def test_create_group_message_success() -> None:
    from app.domain.aggregates.group_dialog import GroupDialog

    owner = uuid7()
    t0 = utc_now()
    group = GroupDialog.create(title="Backend", owner_id=owner, now=t0)

    msg_time = t0 + timedelta(seconds=1)
    msg = MessagePostingPolicy.create_message(
        dialog=group,
        sender_id=owner,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Hello team"),
        position=MessagePosition(dialog_id=group.id, value=1),
        now=msg_time,
    )

    assert msg.dialog_id == group.id
    assert msg.sender_id == owner
    assert msg.created_at == msg_time

    # Default now test
    msg_default = MessagePostingPolicy.create_message(
        dialog=group,
        sender_id=owner,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Default group message"),
        position=MessagePosition(dialog_id=group.id, value=2),
    )
    assert msg_default.created_at >= group.created_at


def test_create_group_message_rejects_outsider() -> None:
    from app.domain.aggregates.group_dialog import GroupDialog
    from app.domain.exceptions.groups import NotGroupMemberError

    owner = uuid7()
    group = GroupDialog.create(title="Backend", owner_id=owner)
    outsider = uuid7()

    with pytest.raises(NotGroupMemberError):
        MessagePostingPolicy.create_message(
            dialog=group,
            sender_id=outsider,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Infiltrating"),
            position=MessagePosition(dialog_id=group.id, value=1),
        )


def test_create_group_message_rejects_preceding_timestamp() -> None:
    from app.domain.aggregates.group_dialog import GroupDialog

    owner = uuid7()
    t0 = utc_now()
    group = GroupDialog.create(title="Backend", owner_id=owner, now=t0)

    with pytest.raises(MessageCreatedAtPrecedesDialogError):
        MessagePostingPolicy.create_message(
            dialog=group,
            sender_id=owner,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Time traveler"),
            position=MessagePosition(dialog_id=group.id, value=1),
            now=t0 - timedelta(seconds=5),
        )


def test_create_group_message_rejects_naive_timestamp() -> None:
    from app.domain.aggregates.group_dialog import GroupDialog

    owner = uuid7()
    group = GroupDialog.create(title="Backend", owner_id=owner)

    with pytest.raises(InvalidDomainTimestampError):
        MessagePostingPolicy.create_message(
            dialog=group,
            sender_id=owner,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Naive"),
            position=MessagePosition(dialog_id=group.id, value=1),
            now=datetime(2026, 9, 23, 12, 0, 0),
        )


def test_create_saved_message_success() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    custom_id = uuid7()
    t0 = utc_now()
    saved = SavedDialog.create(user_id=user_id, now=t0)

    msg_time = t0 + timedelta(seconds=1)
    msg = MessagePostingPolicy.create_message(
        dialog=saved,
        sender_id=user_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Saved note"),
        position=MessagePosition(dialog_id=saved.id, value=1),
        message_id=custom_id,
        now=msg_time,
    )

    assert msg.id == custom_id
    assert msg.dialog_id == saved.id
    assert msg.sender_id == user_id
    assert msg.created_at == msg_time

    # Default message_id and now
    msg_default = MessagePostingPolicy.create_message(
        dialog=saved,
        sender_id=user_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Default note"),
        position=MessagePosition(dialog_id=saved.id, value=2),
    )
    assert msg_default.id.version == 7
    assert msg_default.created_at >= saved.created_at


def test_create_saved_message_rejects_outsider() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    saved = SavedDialog.create(user_id=user_id)
    outsider = uuid7()

    with pytest.raises(NotDialogParticipantError):
        MessagePostingPolicy.create_message(
            dialog=saved,
            sender_id=outsider,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Cannot post in someone else's saved"),
            position=MessagePosition(dialog_id=saved.id, value=1),
        )


def test_create_saved_message_rejects_preceding_timestamp() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    t0 = utc_now()
    saved = SavedDialog.create(user_id=user_id, now=t0)

    with pytest.raises(MessageCreatedAtPrecedesDialogError):
        MessagePostingPolicy.create_message(
            dialog=saved,
            sender_id=user_id,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Before time"),
            position=MessagePosition(dialog_id=saved.id, value=1),
            now=t0 - timedelta(seconds=10),
        )


def test_create_saved_message_rejects_naive_timestamp() -> None:
    from app.domain.aggregates.saved_dialog import SavedDialog

    user_id = uuid7()
    saved = SavedDialog.create(user_id=user_id)

    with pytest.raises(InvalidDomainTimestampError):
        MessagePostingPolicy.create_message(
            dialog=saved,
            sender_id=user_id,
            client_message_id=ClientMessageId.generate(),
            content=MessageContent.from_text("Naive timestamp"),
            position=MessagePosition(dialog_id=saved.id, value=1),
            now=datetime(2026, 9, 23, 12, 0, 0),
        )


def test_message_queries_expose_author_content_and_send_identity() -> None:
    sender = uuid7()
    other_user = uuid7()
    dialog = _create_dialog(user_a=sender, user_b=other_user)
    client_id = ClientMessageId.generate()
    message = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=sender,
        client_message_id=client_id,
        content=MessageContent.from_text("Text"),
        position=_position(dialog, 1),
    )
    assert message.is_sent_by(sender)
    assert not message.is_sent_by(other_user)
    assert message.text_value == "Text"
    assert message.send_key.sender_id == sender
    assert message.send_key.client_message_id == client_id
