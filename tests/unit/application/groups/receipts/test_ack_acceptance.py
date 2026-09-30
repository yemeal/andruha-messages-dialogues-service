import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.advance_receipt.command import (
    AdvanceGroupReceiptCommand,
)
from app.application.commands.groups.remove_member.command import (
    RemoveGroupMemberCommand,
)
from app.application.commands.groups.send_message.command import SendGroupMessageCommand
from app.application.exceptions.groups import MessageNotFoundError
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.exceptions.groups import NotGroupMemberError
from app.domain.exceptions.receipts import NotIncomingMessageError


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["DELIVERED", "READ"])
async def test_ack_is_saved_and_repeated_ack_preserves_watermark_version_and_time(
    send_message,
    advance_receipt,
    groups,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
    kind: str,
) -> None:
    message = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=alice_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000401"),
            text="Входящее",
        )
    )
    command = AdvanceGroupReceiptCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        kind=kind,
        through_message_id=message.message.id,
    )
    first = await advance_receipt(command)
    repeated = await advance_receipt(command)

    assert first.changed is True
    assert repeated.changed is False
    assert repeated.watermark == first.watermark
    assert first.group_version == 1
    assert first.watermark.version == 2
    assert first.watermark.delivered_through.message_id == message.message.id
    if kind == "READ":
        assert first.watermark.read_through == first.watermark.delivered_through
    else:
        assert first.watermark.read_through is None
    assert (await groups.get_receipt(group_id, bob_id)).version == 2


@pytest.mark.asyncio
async def test_even_noop_ack_must_pass_fence_after_concurrent_removal(
    send_message,
    advance_receipt,
    remove_member,
    groups,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    message = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=alice_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000402"),
            text="Сообщение уже прочитано",
        )
    )
    command = AdvanceGroupReceiptCommand(
        dialog_id=group_id,
        actor_id=bob_id,
        kind="READ",
        through_message_id=message.message.id,
    )
    first = await advance_receipt(command)
    groups.pause_type = type(None)
    pending = asyncio.create_task(advance_receipt(command))
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        await remove_member(
            RemoveGroupMemberCommand(
                dialog_id=group_id, actor_id=alice_id, user_id=bob_id
            )
        )
        removal_revision = groups.current.revision
        groups.resume.set()
        with pytest.raises(NotGroupMemberError):
            await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    persisted = await groups.get_receipt(group_id, bob_id)
    assert persisted.version == first.watermark.version
    assert persisted.updated_at == first.watermark.updated_at
    assert groups.current.revision == removal_revision


@pytest.mark.asyncio
async def test_concurrent_lower_ack_cannot_replace_later_read_boundary(
    send_message,
    advance_receipt,
    groups,
    group_id: UUID,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    earlier = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=alice_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000403"),
            text="Первое",
        )
    )
    later = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=alice_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000404"),
            text="Второе",
        )
    )
    groups.pause_type = ReceiptWatermark
    pending = asyncio.create_task(
        advance_receipt(
            AdvanceGroupReceiptCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                kind="READ",
                through_message_id=earlier.message.id,
            )
        )
    )
    try:
        await asyncio.wait_for(groups.entered.wait(), timeout=2)
        winner = await advance_receipt(
            AdvanceGroupReceiptCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                kind="READ",
                through_message_id=later.message.id,
            )
        )
        groups.resume.set()
        retried = await pending
    finally:
        groups.resume.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    assert winner.changed is True
    assert retried.changed is False
    assert retried.watermark == winner.watermark
    assert retried.watermark.read_through.position == 2
    assert (await groups.get_receipt(group_id, bob_id)).version == 2


@pytest.mark.asyncio
async def test_author_cannot_ack_own_message(
    send_message, advance_receipt, groups, group_id: UUID, alice_id: UUID
) -> None:
    message = await send_message(
        SendGroupMessageCommand(
            dialog_id=group_id,
            actor_id=alice_id,
            client_message_id=UUID("01995140-0000-7000-8000-000000000405"),
            text="Исходящее",
        )
    )
    revision = groups.current.revision
    with pytest.raises(NotIncomingMessageError):
        await advance_receipt(
            AdvanceGroupReceiptCommand(
                dialog_id=group_id,
                actor_id=alice_id,
                kind="READ",
                through_message_id=message.message.id,
            )
        )

    assert await groups.get_receipt(group_id, alice_id) is None
    assert groups.current.revision == revision


@pytest.mark.asyncio
async def test_ack_requires_a_persisted_message_in_the_same_dialog(
    advance_receipt, groups, group_id: UUID, bob_id: UUID
) -> None:
    with pytest.raises(MessageNotFoundError):
        await advance_receipt(
            AdvanceGroupReceiptCommand(
                dialog_id=group_id,
                actor_id=bob_id,
                kind="READ",
                through_message_id=UUID("01995140-0000-7000-8000-000000000499"),
            )
        )

    assert await groups.get_receipt(group_id, bob_id) is None
    assert groups.current.revision == 1
