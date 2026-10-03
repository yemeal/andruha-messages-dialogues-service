from uuid import UUID

import pytest

from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
)
from app.application.commands.groups.advance_receipt.handler import (
    AdvanceGroupReceiptHandler,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition


@pytest.mark.asyncio
async def test_commit_rejects_duplicate_send_key_even_with_a_fresh_group_revision(
    groups, send_message, clock, ids, group_id: UUID, bob_id: UUID
) -> None:
    accepted = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000730"),
            text="One logical send",
        )
    )
    stored = groups.messages[accepted.message.id]
    snapshot = await groups.get_by_id(group_id)
    duplicate = Message.create(
        dialog_id=group_id,
        sender_id=bob_id,
        client_message_id=stored.client_message_id,
        content=MessageContent.from_text("A duplicate candidate"),
        position=MessagePosition(dialog_id=group_id, value=2),
        message_id=ids.new_id(),
        now=clock.now(),
    )

    committed = await groups.try_commit(snapshot, duplicate, command_id=ids.new_id())

    assert committed is False
    assert len(groups.messages) == 1
    assert groups.messages[accepted.message.id] == stored
    assert groups.current.revision == snapshot.revision
    assert groups.current.last_position == 1


@pytest.mark.asyncio
async def test_commit_rejects_receipt_regression_even_with_fresh_group_and_next_version(
    groups,
    send_message,
    clock,
    ids,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    advance_receipt = AdvanceGroupReceiptHandler(groups, clock.now, ids.new_id)
    messages = []
    for value in range(3):
        accepted = await send_message(
            SendGroupMessageCommand(
                dialog_id=group_id,
                actor_id=alice_id,
                client_message_id=UUID(int=value + 740, version=7),
                text=f"Message {value + 1}",
            )
        )
        messages.append(groups.messages[accepted.message.id])
    await advance_receipt(
        AdvanceGroupReceiptCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            kind="READ",
            through_message_id=messages[0].id,
        )
    )
    older = groups.receipts[bob_id].model_copy(deep=True)
    await advance_receipt(
        AdvanceGroupReceiptCommand(
            dialog_id=group_id,
            actor_id=bob_id,
            kind="READ",
            through_message_id=messages[2].id,
        )
    )
    saved = groups.receipts[bob_id]
    before = saved.model_dump()
    older.advance_read(
        actor_id=bob_id,
        dialog=groups.current.dialog,
        through=messages[1],
        now=clock.now(),
    )
    candidate = ReceiptWatermark.model_validate(
        {**older.model_dump(), "version": saved.version + 1}
    )
    snapshot = await groups.get_by_id(group_id)

    committed = await groups.try_commit(snapshot, candidate, command_id=ids.new_id())

    assert committed is False
    assert groups.receipts[bob_id].model_dump() == before
    assert groups.current.revision == snapshot.revision
