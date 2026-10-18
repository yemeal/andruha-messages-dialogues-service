from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest

from app.application.commands.dialogues.advance_direct_receipt.command import (
    AdvanceDirectReceiptCommand,
    ReceiptKind,
)
from app.application.commands.dialogues.advance_direct_receipt.handler import (
    AdvanceDirectReceiptHandler,
)
from app.application.exceptions.groups import DialogNotFoundError
from app.application.ports.persistence.repositories.direct_dialogues import (
    DirectDialogRepositoryProtocol,
)
from app.application.ports.persistence.repositories.direct_messages import (
    DirectMessageRepositoryProtocol,
)
from app.application.ports.persistence.repositories.direct_receipts import (
    DirectReceiptRepositoryProtocol,
)
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.direct_participants import DirectParticipants
from app.domain.value_objects.message_send_key import MessageSendKey


class InMemoryDirectDialogRepository(DirectDialogRepositoryProtocol):
    def __init__(self) -> None:
        self.dialogs: dict[UUID, DirectDialog] = {}

    async def get_by_id(self, dialog_id: UUID) -> DirectDialog | None:
        return self.dialogs.get(dialog_id)

    async def get_by_participants(
        self, participants: DirectParticipants
    ) -> DirectDialog | None:
        for dialog in self.dialogs.values():
            if dialog.participants == participants:
                return dialog
        return None

    async def create_or_get(self, candidate: DirectDialog):
        existing = await self.get_by_participants(candidate.participants)
        if existing is not None:
            from app.application.ports.persistence.models import CanonicalDialog

            return CanonicalDialog(dialog=existing, created=False)
        self.dialogs[candidate.id] = candidate
        from app.application.ports.persistence.models import CanonicalDialog

        return CanonicalDialog(dialog=candidate, created=True)


class InMemoryDirectMessageRepository(DirectMessageRepositoryProtocol):
    def __init__(self) -> None:
        self.messages_by_send_key: dict[MessageSendKey, Message] = {}
        self.messages_by_id: dict[tuple[UUID, UUID], Message] = {}
        self.last_positions: dict[UUID, int] = {}

    async def get_by_send_key(self, send_key: MessageSendKey) -> Message | None:
        return self.messages_by_send_key.get(send_key)

    async def get_last_position(self, dialog_id: UUID) -> int:
        return self.last_positions.get(dialog_id, 0)

    async def get_message_by_id(
        self, dialog_id: UUID, message_id: UUID
    ) -> Message | None:
        return self.messages_by_id.get((dialog_id, message_id))

    async def save_message(
        self, message: Message, *, idempotency_key: MessageSendKey
    ) -> Message:
        self.messages_by_send_key[idempotency_key] = message
        self.messages_by_id[(message.dialog_id, message.id)] = message
        self.last_positions[message.dialog_id] = message.position.value
        return message


class InMemoryDirectReceiptRepository(DirectReceiptRepositoryProtocol):
    def __init__(self) -> None:
        self.watermarks: dict[tuple[UUID, UUID], ReceiptWatermark] = {}
        self.fail_save: bool = False

    async def get_watermark(
        self, dialog_id: UUID, user_id: UUID
    ) -> ReceiptWatermark | None:
        existing = self.watermarks.get((dialog_id, user_id))
        return existing.model_copy(deep=True) if existing else None

    async def save_watermark(
        self, watermark: ReceiptWatermark, *, expected_version: int
    ) -> bool:
        if self.fail_save:
            return False
        existing = self.watermarks.get((watermark.dialog_id, watermark.user_id))
        current_version = existing.version if existing is not None else 0
        if current_version != expected_version:
            return False
        self.watermarks[(watermark.dialog_id, watermark.user_id)] = (
            watermark.model_copy(deep=True)
        )
        return True


@pytest.fixture
def alice_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def bob_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def direct_repo() -> InMemoryDirectDialogRepository:
    return InMemoryDirectDialogRepository()


@pytest.fixture
def message_repo() -> InMemoryDirectMessageRepository:
    return InMemoryDirectMessageRepository()


@pytest.fixture
def receipt_repo() -> InMemoryDirectReceiptRepository:
    return InMemoryDirectReceiptRepository()


@pytest.fixture
def handler(
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    receipt_repo: InMemoryDirectReceiptRepository,
) -> AdvanceDirectReceiptHandler:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    return AdvanceDirectReceiptHandler(
        direct_dialogs=direct_repo,
        direct_messages=message_repo,
        direct_receipts=receipt_repo,
        clock=lambda: now,
        ids=uuid7,
    )


@pytest.mark.asyncio
async def test_advance_direct_receipt_dialog_not_found(
    handler: AdvanceDirectReceiptHandler, alice_id: UUID
) -> None:
    unknown_dialog_id = uuid7()
    command = AdvanceDirectReceiptCommand(
        dialog_id=unknown_dialog_id,
        actor_id=alice_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=uuid7(),
    )
    with pytest.raises(DialogNotFoundError):
        await handler(command)


@pytest.mark.asyncio
async def test_advance_direct_receipt_non_participant(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.dialogues import NotDialogParticipantError

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    charlie_id = UUID("00000000-0000-4000-8000-000000000003")
    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=charlie_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=uuid7(),
    )
    with pytest.raises(NotDialogParticipantError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_advance_direct_receipt_message_not_found(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import MessageNotFoundError

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=uuid7(),
    )
    with pytest.raises(MessageNotFoundError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_advance_direct_receipt_cannot_ack_own_message(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.receipts import NotIncomingMessageError
    from app.domain.policies.message_posting import MessagePostingPolicy
    from app.domain.value_objects.client_message_id import ClientMessageId
    from app.domain.value_objects.message_content import MessageContent
    from app.domain.value_objects.message_position import MessagePosition

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Alice says hi"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        message_id=uuid7(),
    )
    await message_repo.save_message(msg, idempotency_key=msg.send_key)

    # Alice tries to ACK her own message
    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=msg.id,
    )
    with pytest.raises(NotIncomingMessageError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_advance_direct_receipt_delivered_success(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.policies.message_posting import MessagePostingPolicy
    from app.domain.value_objects.client_message_id import ClientMessageId
    from app.domain.value_objects.message_content import MessageContent
    from app.domain.value_objects.message_position import MessagePosition

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Alice to Bob"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        message_id=uuid7(),
    )
    await message_repo.save_message(msg, idempotency_key=msg.send_key)

    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=msg.id,
    )
    res = await handler(cmd)
    assert res.changed is True
    assert res.watermark.delivered_through is not None
    assert res.watermark.delivered_through.message_id == msg.id
    assert res.watermark.delivered_through.position == 1
    assert res.watermark.read_through is None


@pytest.mark.asyncio
async def test_advance_direct_receipt_read_pulls_delivered(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.policies.message_posting import MessagePostingPolicy
    from app.domain.value_objects.client_message_id import ClientMessageId
    from app.domain.value_objects.message_content import MessageContent
    from app.domain.value_objects.message_position import MessagePosition

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Alice to Bob"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        message_id=uuid7(),
    )
    await message_repo.save_message(msg, idempotency_key=msg.send_key)

    # Bob directly marks READ without prior DELIVERED
    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        kind=ReceiptKind.READ,
        through_message_id=msg.id,
    )
    res = await handler(cmd)
    assert res.changed is True
    assert res.watermark.read_through is not None
    assert res.watermark.read_through.message_id == msg.id
    assert res.watermark.delivered_through is not None
    assert res.watermark.delivered_through.message_id == msg.id


@pytest.mark.asyncio
async def test_advance_direct_receipt_no_op_duplicate(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.policies.message_posting import MessagePostingPolicy
    from app.domain.value_objects.client_message_id import ClientMessageId
    from app.domain.value_objects.message_content import MessageContent
    from app.domain.value_objects.message_position import MessagePosition

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Alice to Bob"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        message_id=uuid7(),
    )
    await message_repo.save_message(msg, idempotency_key=msg.send_key)

    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        kind=ReceiptKind.READ,
        through_message_id=msg.id,
    )
    first = await handler(cmd)
    assert first.changed is True

    # Replay same ACK
    second = await handler(cmd)
    assert second.changed is False
    assert second.watermark.version == first.watermark.version


@pytest.mark.asyncio
async def test_advance_direct_receipt_version_conflict_raises_error(
    handler: AdvanceDirectReceiptHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    receipt_repo: InMemoryDirectReceiptRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import ConcurrentModificationError
    from app.domain.policies.message_posting import MessagePostingPolicy
    from app.domain.value_objects.client_message_id import ClientMessageId
    from app.domain.value_objects.message_content import MessageContent
    from app.domain.value_objects.message_position import MessagePosition

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    msg = MessagePostingPolicy.create_message(
        dialog=dialog,
        sender_id=alice_id,
        client_message_id=ClientMessageId.from_uuid(uuid7()),
        content=MessageContent.from_parts(text="Alice to Bob"),
        position=MessagePosition(dialog_id=dialog.id, value=1),
        message_id=uuid7(),
    )
    await message_repo.save_message(msg, idempotency_key=msg.send_key)

    receipt_repo.fail_save = True
    cmd = AdvanceDirectReceiptCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        kind=ReceiptKind.DELIVERED,
        through_message_id=msg.id,
    )
    with pytest.raises(ConcurrentModificationError):
        await handler(cmd)
