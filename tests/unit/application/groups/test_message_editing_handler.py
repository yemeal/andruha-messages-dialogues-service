from uuid import UUID

import pytest

from app.application.commands.groups.edit_message.command import (
    EditGroupMessageTextCommand,
)
from app.application.commands.groups.edit_message.handler import (
    EditGroupMessageTextHandler,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.ports.persistence.models import GroupMutation, GroupSnapshot
from app.domain.aggregates.message import Message
from app.domain.value_objects.message_send_key import MessageSendKey


class MessageEditingGroupsWrapper:
    """Обертка над fixture groups с реализацией get_message_by_id и CAS-редактирования сообщений."""

    def __init__(self, groups) -> None:
        self._groups = groups

    @property
    def current(self) -> GroupSnapshot:
        return self._groups.current

    @property
    def messages(self) -> dict[UUID, Message]:
        return self._groups.messages

    @property
    def force_conflict(self) -> bool:
        return self._groups.force_conflict

    @force_conflict.setter
    def force_conflict(self, value: bool) -> None:
        self._groups.force_conflict = value

    async def get_by_id(self, dialog_id: UUID) -> GroupSnapshot | None:
        return await self._groups.get_by_id(dialog_id)

    async def get_message_by_id(
        self, dialog_id: UUID, message_id: UUID, *, at_revision: int | None = None
    ) -> Message | None:
        return await self._groups.get_message(
            dialog_id, message_id, at_revision=at_revision
        )

    async def get_sent_message(
        self,
        dialog_id: UUID,
        send_key: MessageSendKey,
        *,
        at_revision: int | None = None,
    ) -> Message | None:
        return await self._groups.get_sent_message(
            dialog_id, send_key, at_revision=at_revision
        )

    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        if self._groups.force_conflict:
            return False

        async with self._groups.lock:
            if expected.revision != self._groups.current.revision:
                return False

            if isinstance(mutation, Message) and mutation.id in self._groups.messages:
                existing = self._groups.messages[mutation.id]
                if (
                    mutation.dialog_id != self._groups.current.dialog.id
                    or mutation.version != existing.version + 1
                    or mutation.sender_id != existing.sender_id
                    or mutation.client_message_id != existing.client_message_id
                    or mutation.position != existing.position
                    or mutation.created_at != existing.created_at
                ):
                    return False

                self._groups.messages[mutation.id] = mutation.model_copy(deep=True)
                self._groups.current = GroupSnapshot(
                    dialog=self._groups.current.dialog,
                    revision=self._groups.current.revision + 1,
                    last_position=self._groups.current.last_position,
                )
                return True

        return await self._groups.try_commit(expected, mutation, command_id=command_id)


@pytest.fixture
def editing_groups(groups) -> MessageEditingGroupsWrapper:
    return MessageEditingGroupsWrapper(groups)


@pytest.mark.asyncio
async def test_author_successfully_edits_group_message_text(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    # 1. Отправляем первоначальное сообщение от имени Bob
    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000701"),
            text="Original message text",
        )
    )
    message_id = sent.message.id
    assert sent.message.version == 1
    assert sent.message.edited_at is None
    initial_revision = editing_groups.current.revision

    # 2. Bob редактирует текст сообщения
    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)
    command_id = UUID("01995140-0000-7000-8000-000000000901")

    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text="Edited message text",
        command_id=command_id,
    )

    result = await handler(cmd)

    # 3. Проверяем возвращённый результат
    assert result.changed is True
    assert result.message.id == message_id
    assert result.message.text == "Edited message text"
    assert result.message.version == 2
    assert result.message.edited_at == clock.now()
    assert result.group_version == 1

    # 4. Проверяем состояние в хранилище
    saved = await editing_groups.get_message_by_id(
        group_id, message_id, at_revision=initial_revision + 1
    )
    assert saved is not None
    assert saved.text_value == "Edited message text"
    assert saved.version == 2
    assert saved.is_edited is True
    assert saved.edited_at == clock.now()
    assert editing_groups.current.revision == initial_revision + 1


@pytest.mark.asyncio
async def test_repeated_edit_with_same_text_returns_changed_false(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    # 1. Отправляем сообщение
    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000702"),
            text="Stable text",
        )
    )
    message_id = sent.message.id

    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    # 2. Повторяем тот же самый текст
    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text="Stable text",
        command_id=UUID("01995140-0000-7000-8000-000000000902"),
    )

    result = await handler(cmd)

    # 3. changed=False, версия и edited_at не меняются
    assert result.changed is False
    assert result.message.id == message_id
    assert result.message.text == "Stable text"
    assert result.message.version == 1
    assert result.message.edited_at is None

    # В репозитории сообщение не изменилось
    saved = await editing_groups.get_message_by_id(
        group_id, message_id, at_revision=editing_groups.current.revision
    )
    assert saved is not None
    assert saved.version == 1
    assert saved.edited_at is None


@pytest.mark.asyncio
async def test_non_author_cannot_edit_message_raises_error(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.messages import NotMessageAuthorError

    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000703"),
            text="Bob's original text",
        )
    )
    message_id = sent.message.id

    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    # Alice пытается отредактировать сообщение Боба
    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=alice_id,
        message_id=message_id,
        new_text="Alice's edit attempt",
        command_id=UUID("01995140-0000-7000-8000-000000000903"),
    )

    with pytest.raises(NotMessageAuthorError):
        await handler(cmd)

    # Сообщение не изменилось
    saved = await editing_groups.get_message_by_id(
        group_id, message_id, at_revision=editing_groups.current.revision
    )
    assert saved is not None
    assert saved.text_value == "Bob's original text"
    assert saved.version == 1


@pytest.mark.asyncio
async def test_non_member_cannot_edit_message_raises_error(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.groups import NotGroupMemberError

    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000704"),
            text="Member text",
        )
    )
    message_id = sent.message.id

    stranger_id = UUID("00000000-0000-4000-8000-000000000999")
    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=stranger_id,
        message_id=message_id,
        new_text="Hacked text",
        command_id=UUID("01995140-0000-7000-8000-000000000904"),
    )

    with pytest.raises(NotGroupMemberError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_non_existent_message_raises_error(
    editing_groups: MessageEditingGroupsWrapper,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import MessageNotFoundError

    non_existent_id = UUID("01995140-0000-7000-8000-000000000999")
    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=non_existent_id,
        new_text="New text",
        command_id=UUID("01995140-0000-7000-8000-000000000905"),
    )

    with pytest.raises(MessageNotFoundError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_non_existent_dialog_raises_error(
    editing_groups: MessageEditingGroupsWrapper,
    clock,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import DialogNotFoundError

    non_existent_dialog_id = UUID("01995140-0000-7000-8000-000000000998")
    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    cmd = EditGroupMessageTextCommand(
        dialog_id=non_existent_dialog_id,
        actor_id=bob_id,
        message_id=UUID("01995140-0000-7000-8000-000000000999"),
        new_text="New text",
        command_id=UUID("01995140-0000-7000-8000-000000000906"),
    )

    with pytest.raises(DialogNotFoundError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_empty_message_without_attachments_raises_error(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.messages import EmptyMessageContentError

    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000705"),
            text="Initial text without attachments",
        )
    )
    message_id = sent.message.id

    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    # Попытка стереть текст в пустую строку или None
    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text="   ",
        command_id=UUID("01995140-0000-7000-8000-000000000907"),
    )

    with pytest.raises(EmptyMessageContentError):
        await handler(cmd)

    # И с явным None
    cmd_none = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text=None,
        command_id=UUID("01995140-0000-7000-8000-000000000908"),
    )

    with pytest.raises(EmptyMessageContentError):
        await handler(cmd_none)


@pytest.mark.asyncio
async def test_clearing_text_with_attachments_succeeds(
    editing_groups: MessageEditingGroupsWrapper,
    clock,
    ids,
    make_attachments,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.commands.groups.send_message.handler import (
        SendGroupMessageHandler,
    )
    from app.domain.value_objects.object_id import ObjectId

    attachment_id = UUID("01995140-0000-7000-8000-000000000888")
    sender = SendGroupMessageHandler(
        groups=editing_groups,
        clock=clock.now,
        ids=ids.new_id,
        attachments=make_attachments({ObjectId.from_uuid(attachment_id)}),
    )
    sent = await sender(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000706"),
            text="Photo caption",
            attachment_ids=(attachment_id,),
        )
    )
    message_id = sent.message.id

    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text=None,
        command_id=UUID("01995140-0000-7000-8000-000000000909"),
    )

    result = await handler(cmd)

    assert result.changed is True
    assert result.message.text is None
    assert result.message.attachment_ids == (attachment_id,)
    assert result.message.version == 2
    assert result.message.edited_at == clock.now()


@pytest.mark.asyncio
async def test_edit_group_message_concurrent_exhaustion(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import ConcurrentModificationError

    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000707"),
            text="Initial text",
        )
    )
    message_id = sent.message.id

    editing_groups.force_conflict = True
    handler = EditGroupMessageTextHandler(
        groups=editing_groups, clock=clock.now, max_attempts=3
    )

    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text="Never committed",
        command_id=UUID("01995140-0000-7000-8000-000000000910"),
    )

    with pytest.raises(ConcurrentModificationError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_edit_group_message_read_conflict_retries_and_succeeds(
    editing_groups: MessageEditingGroupsWrapper,
    send_message,
    clock,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import GroupReadConflictError

    sent = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000708"),
            text="Text before read conflict",
        )
    )
    message_id = sent.message.id

    real_get_message_by_id = editing_groups.get_message_by_id
    call_count = 0

    async def flaky_get_message_by_id(dialog_id, msg_id, *, at_revision=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise GroupReadConflictError("Stale read")
        return await real_get_message_by_id(dialog_id, msg_id, at_revision=at_revision)

    editing_groups.get_message_by_id = flaky_get_message_by_id  # type: ignore[method-assign]

    handler = EditGroupMessageTextHandler(groups=editing_groups, clock=clock.now)

    cmd = EditGroupMessageTextCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        message_id=message_id,
        new_text="Text after read retry",
        command_id=UUID("01995140-0000-7000-8000-000000000911"),
    )

    result = await handler(cmd)

    assert result.changed is True
    assert result.message.text == "Text after read retry"
    assert call_count >= 2


def test_edit_group_message_handler_validates_max_attempts(
    editing_groups: MessageEditingGroupsWrapper,
    clock,
) -> None:
    with pytest.raises(ValueError, match="max_attempts must be positive"):
        EditGroupMessageTextHandler(
            groups=editing_groups, clock=clock.now, max_attempts=0
        )
