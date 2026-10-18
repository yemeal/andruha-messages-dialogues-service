from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest

from app.application.commands.dialogues.send_saved_message.command import (
    SendSavedMessageCommand,
)
from app.application.commands.dialogues.send_saved_message.handler import (
    SendSavedMessageHandler,
)
from app.application.exceptions.groups import DialogNotFoundError
from app.application.ports.objects.attachments import AttachmentVerifierProtocol
from app.application.ports.persistence.repositories.direct_messages import (
    DirectMessageRepositoryProtocol,
)
from app.application.ports.persistence.repositories.saved_dialogues import (
    SavedDialogRepositoryProtocol,
)
from app.domain.aggregates.message import Message
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.message_send_key import MessageSendKey


class InMemorySavedDialogRepository(SavedDialogRepositoryProtocol):
    def __init__(self) -> None:
        self.dialogs_by_id: dict[UUID, SavedDialog] = {}
        self.dialogs_by_owner: dict[UUID, SavedDialog] = {}

    async def get_by_id(self, dialog_id: UUID) -> SavedDialog | None:
        return self.dialogs_by_id.get(dialog_id)

    async def get_by_owner(self, user_id: UUID) -> SavedDialog | None:
        return self.dialogs_by_owner.get(user_id)

    async def create_or_get(self, candidate: SavedDialog):
        existing = await self.get_by_owner(candidate.user_id)
        if existing is not None:
            from app.application.ports.persistence.models import CanonicalDialog

            return CanonicalDialog(dialog=existing, created=False)
        self.dialogs_by_id[candidate.id] = candidate
        self.dialogs_by_owner[candidate.user_id] = candidate
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


class DummyAttachmentVerifier(AttachmentVerifierProtocol):
    def __init__(self) -> None:
        self.verified: list[tuple[UUID, tuple]] = []

    async def require_ready(self, actor_id: UUID, attachments: tuple) -> None:
        self.verified.append((actor_id, attachments))


@pytest.fixture
def alice_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def bob_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def saved_repo() -> InMemorySavedDialogRepository:
    return InMemorySavedDialogRepository()


@pytest.fixture
def message_repo() -> InMemoryDirectMessageRepository:
    return InMemoryDirectMessageRepository()


@pytest.fixture
def attachment_verifier() -> DummyAttachmentVerifier:
    return DummyAttachmentVerifier()


@pytest.fixture
def handler(
    saved_repo: InMemorySavedDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    attachment_verifier: DummyAttachmentVerifier,
) -> SendSavedMessageHandler:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    return SendSavedMessageHandler(
        saved_dialogs=saved_repo,
        messages=message_repo,
        attachments=attachment_verifier,
        clock=lambda: now,
        ids=uuid7,
    )


@pytest.mark.asyncio
async def test_send_saved_message_dialog_not_found(
    handler: SendSavedMessageHandler, alice_id: UUID
) -> None:
    unknown_dialog_id = uuid7()
    command = SendSavedMessageCommand(
        dialog_id=unknown_dialog_id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="My note",
    )
    with pytest.raises(DialogNotFoundError):
        await handler(command)


@pytest.mark.asyncio
async def test_send_saved_message_not_owner(
    handler: SendSavedMessageHandler,
    saved_repo: InMemorySavedDialogRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.dialogues import NotDialogParticipantError

    dialog = SavedDialog.create(user_id=alice_id)
    await saved_repo.create_or_get(dialog)

    cmd = SendSavedMessageCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        client_message_id=uuid7(),
        text="Intruding Bob",
    )
    with pytest.raises(NotDialogParticipantError):
        await handler(cmd)


@pytest.mark.asyncio
async def test_send_saved_message_success_monotone_positions(
    handler: SendSavedMessageHandler,
    saved_repo: InMemorySavedDialogRepository,
    alice_id: UUID,
) -> None:
    dialog = SavedDialog.create(user_id=alice_id)
    await saved_repo.create_or_get(dialog)

    cmd1 = SendSavedMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="Note 1",
    )
    result1 = await handler(cmd1)
    assert result1.message.dialog_id == dialog.id
    assert result1.message.sender_id == alice_id
    assert result1.message.position == 1
    assert result1.message.text == "Note 1"

    cmd2 = SendSavedMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="Note 2",
    )
    result2 = await handler(cmd2)
    assert result2.message.dialog_id == dialog.id
    assert result2.message.position == 2
    assert result2.message.text == "Note 2"


@pytest.mark.asyncio
async def test_send_saved_message_with_attachments(
    handler: SendSavedMessageHandler,
    saved_repo: InMemorySavedDialogRepository,
    attachment_verifier: DummyAttachmentVerifier,
    alice_id: UUID,
) -> None:
    from app.domain.value_objects.object_id import ObjectId

    dialog = SavedDialog.create(user_id=alice_id)
    await saved_repo.create_or_get(dialog)

    att_id = uuid7()
    cmd = SendSavedMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="Saved image",
        attachment_ids=(att_id,),
    )
    result = await handler(cmd)
    assert result.message.attachment_ids == (att_id,)
    assert len(attachment_verifier.verified) == 1
    assert attachment_verifier.verified[0] == (
        alice_id,
        (ObjectId.from_uuid(att_id),),
    )


@pytest.mark.asyncio
async def test_send_saved_message_idempotent_replay_and_conflict(
    handler: SendSavedMessageHandler,
    saved_repo: InMemorySavedDialogRepository,
    alice_id: UUID,
) -> None:
    from app.application.exceptions.groups import MessageSendConflictError

    dialog = SavedDialog.create(user_id=alice_id)
    await saved_repo.create_or_get(dialog)

    client_id = uuid7()
    cmd = SendSavedMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=client_id,
        text="Note to self",
    )
    first = await handler(cmd)
    second = await handler(cmd)

    assert first.message.id == second.message.id
    assert first.message.position == second.message.position == 1

    conflict_cmd = SendSavedMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=client_id,
        text="Conflicting note to self",
    )
    with pytest.raises(MessageSendConflictError):
        await handler(conflict_cmd)


@pytest.mark.asyncio
async def test_saved_dialog_does_not_support_receipts(
    saved_repo: InMemorySavedDialogRepository,
    alice_id: UUID,
) -> None:
    dialog = SavedDialog.create(user_id=alice_id)
    assert dialog.supports_receipts is False
