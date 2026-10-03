from uuid import UUID

import pytest

from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.commands.groups.send_message.handler import SendGroupMessageHandler
from app.application.exceptions.groups import (
    ConcurrentModificationError,
    GroupReadConflictError,
)
from app.application.ports.persistence.models import GroupMutation, GroupSnapshot
from app.domain.value_objects.message_send_key import MessageSendKey
from app.domain.value_objects.object_id import ObjectId


class StaleSendReads:
    """Первая реплика send-key ещё не догнала прочитанную ревизию группы."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self.stale = True

    async def get_by_id(self, dialog_id: UUID):
        return await self.repository.get_by_id(dialog_id)

    async def get_sent_message(
        self,
        dialog_id: UUID,
        send_key: MessageSendKey,
        *,
        at_revision: int | None = None,
    ):
        if self.stale:
            self.stale = False
            if at_revision is None:
                return None
            raise GroupReadConflictError("Send-key replica has an older revision")
        return await self.repository.get_sent_message(
            dialog_id, send_key, at_revision=at_revision
        )

    async def try_commit(
        self, expected: GroupSnapshot, mutation: GroupMutation, *, command_id: UUID
    ) -> bool:
        return await self.repository.try_commit(
            expected, mutation, command_id=command_id
        )


class NoAttachments:
    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        raise AssertionError("This scenario has no attachments")


@pytest.mark.asyncio
async def test_stale_send_key_read_cannot_create_a_second_message(
    groups, send_message, clock, ids, group_id: UUID, bob_id: UUID
) -> None:
    command = SendGroupMessageCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        client_message_id=UUID("01995140-0000-7000-8000-000000000710"),
        text="One logical send",
    )
    accepted = await send_message(command)
    handler = SendGroupMessageHandler(
        StaleSendReads(groups), clock.now, ids.new_id, NoAttachments()
    )

    replay = await handler(command)

    assert replay.message.id == accepted.message.id
    assert replay.message.position == 1
    assert len(groups.messages) == 1
    assert groups.current.last_position == 1


class UnavailableRevisionReads(StaleSendReads):
    def __init__(self, repository) -> None:
        super().__init__(repository)
        self.reads = 0

    async def get_sent_message(
        self, dialog_id: UUID, send_key: MessageSendKey, *, at_revision: int
    ):
        self.reads += 1
        raise GroupReadConflictError("Requested revision cannot be read")


@pytest.mark.asyncio
async def test_read_conflicts_are_bounded_without_creating_a_message(
    groups,
    clock,
    ids,
    group_id: UUID,
    bob_id: UUID,
) -> None:
    repository = UnavailableRevisionReads(groups)
    handler = SendGroupMessageHandler(
        repository, clock.now, ids.new_id, NoAttachments(), max_attempts=2
    )

    with pytest.raises(ConcurrentModificationError):
        await handler(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                client_message_id=UUID("01995140-0000-7000-8000-000000000711"),
                text="A send without a consistent read",
            )
        )

    assert repository.reads == 2
    assert groups.messages == {}
    assert groups.current.revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["send-key", "message", "receipt"])
async def test_reading_an_absent_record_on_an_old_revision_is_a_conflict(
    groups,
    ids,
    group_id: UUID,
    bob_id: UUID,
    reader: str,
) -> None:
    snapshot = await groups.get_by_id(group_id)
    assert await groups.try_commit(snapshot, None, command_id=ids.new_id())

    with pytest.raises(GroupReadConflictError):
        if reader == "send-key":
            from app.domain.value_objects.client_message_id import ClientMessageId

            await groups.get_sent_message(
                group_id,
                MessageSendKey(
                    sender_id=bob_id,
                    client_message_id=ClientMessageId.from_uuid(ids.new_id()),
                ),
                at_revision=snapshot.revision,
            )
        elif reader == "message":
            await groups.get_message(
                group_id, ids.new_id(), at_revision=snapshot.revision
            )
        else:
            await groups.get_receipt(group_id, bob_id, at_revision=snapshot.revision)

    assert groups.messages == {}
    assert groups.receipts == {}
