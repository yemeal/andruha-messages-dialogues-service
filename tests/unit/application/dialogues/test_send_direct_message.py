from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest

from app.application.commands.dialogues.send_direct_message.command import (
    SendDirectMessageCommand,
)
from app.application.commands.dialogues.send_direct_message.handler import (
    SendDirectMessageHandler,
)
from app.application.exceptions.groups import DialogNotFoundError
from app.application.ports.objects.attachments import AttachmentVerifierProtocol
from app.application.ports.persistence.repositories.direct_dialogues import (
    DirectDialogRepositoryProtocol,
)
from app.application.ports.persistence.repositories.direct_messages import (
    DirectMessageRepositoryProtocol,
)
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.message import Message
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
def direct_repo() -> InMemoryDirectDialogRepository:
    return InMemoryDirectDialogRepository()


@pytest.fixture
def message_repo() -> InMemoryDirectMessageRepository:
    return InMemoryDirectMessageRepository()


@pytest.fixture
def attachment_verifier() -> DummyAttachmentVerifier:
    return DummyAttachmentVerifier()


@pytest.fixture
def handler(
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    attachment_verifier: DummyAttachmentVerifier,
) -> SendDirectMessageHandler:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    return SendDirectMessageHandler(
        direct_dialogs=direct_repo,
        direct_messages=message_repo,
        attachments=attachment_verifier,
        clock=lambda: now,
        ids=uuid7,
    )


@pytest.mark.asyncio
async def test_send_direct_message_dialog_not_found(
    handler: SendDirectMessageHandler, alice_id: UUID
) -> None:
    unknown_dialog_id = uuid7()
    command = SendDirectMessageCommand(
        dialog_id=unknown_dialog_id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="Hello Bob!",
    )
    with pytest.raises(DialogNotFoundError):
        await handler(command)


@pytest.mark.asyncio
async def test_send_direct_message_not_participant(
    handler: SendDirectMessageHandler,
    direct_repo: InMemoryDirectDialogRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.domain.exceptions.dialogues import NotDialogParticipantError

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    charlie_id = UUID("00000000-0000-4000-8000-000000000003")
    command = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=charlie_id,
        client_message_id=uuid7(),
        text="Spying!",
    )
    with pytest.raises(NotDialogParticipantError):
        await handler(command)


@pytest.mark.asyncio
async def test_send_direct_message_success_monotone_positions(
    handler: SendDirectMessageHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    cmd1 = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="Hello Bob!",
    )
    result1 = await handler(cmd1)
    assert result1.message.dialog_id == dialog.id
    assert result1.message.sender_id == alice_id
    assert result1.message.position == 1
    assert result1.message.text == "Hello Bob!"
    assert result1.message.version == 1

    cmd2 = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=bob_id,
        client_message_id=uuid7(),
        text="Hi Alice!",
    )
    result2 = await handler(cmd2)
    assert result2.message.dialog_id == dialog.id
    assert result2.message.sender_id == bob_id
    assert result2.message.position == 2
    assert result2.message.text == "Hi Alice!"


@pytest.mark.asyncio
async def test_send_direct_message_with_attachments(
    handler: SendDirectMessageHandler,
    direct_repo: InMemoryDirectDialogRepository,
    attachment_verifier: DummyAttachmentVerifier,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    att_id = uuid7()
    cmd = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=uuid7(),
        text="Look at this",
        attachment_ids=(att_id,),
    )
    from app.domain.value_objects.object_id import ObjectId

    result = await handler(cmd)
    assert result.message.attachment_ids == (att_id,)
    assert len(attachment_verifier.verified) == 1
    assert attachment_verifier.verified[0] == (
        alice_id,
        (ObjectId.from_uuid(att_id),),
    )


@pytest.mark.asyncio
async def test_send_direct_message_idempotent_replay(
    handler: SendDirectMessageHandler,
    direct_repo: InMemoryDirectDialogRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    client_id = uuid7()
    cmd = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=client_id,
        text="Hello!",
    )
    first = await handler(cmd)
    second = await handler(cmd)

    assert first.message.id == second.message.id
    assert first.message.position == second.message.position == 1


@pytest.mark.asyncio
async def test_send_direct_message_send_conflict_raises_error(
    handler: SendDirectMessageHandler,
    direct_repo: InMemoryDirectDialogRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    from app.application.exceptions.groups import MessageSendConflictError

    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    client_id = uuid7()
    cmd1 = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=client_id,
        text="Hello!",
    )
    await handler(cmd1)

    cmd2 = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=client_id,
        text="Completely different intent!",
    )
    with pytest.raises(MessageSendConflictError):
        await handler(cmd2)


@pytest.mark.asyncio
async def test_send_direct_message_replay_after_edit(
    handler: SendDirectMessageHandler,
    direct_repo: InMemoryDirectDialogRepository,
    message_repo: InMemoryDirectMessageRepository,
    alice_id: UUID,
    bob_id: UUID,
) -> None:
    participants = DirectParticipants.from_user_ids(alice_id, bob_id)
    dialog = DirectDialog.create(participants=participants)
    await direct_repo.create_or_get(dialog)

    client_id = uuid7()
    cmd = SendDirectMessageCommand(
        dialog_id=dialog.id,
        actor_id=alice_id,
        client_message_id=client_id,
        text="Original text",
    )
    first = await handler(cmd)

    # Simulate message edited
    stored_message = await message_repo.get_message_by_id(dialog.id, first.message.id)
    assert stored_message is not None
    now_edit = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
    stored_message.edit_text(actor_id=alice_id, text="Edited text", now=now_edit)

    # Replay with original text
    replay = await handler(cmd)
    assert replay.message.id == first.message.id
    assert replay.message.text == "Edited text"
    assert replay.message.is_edited is True
