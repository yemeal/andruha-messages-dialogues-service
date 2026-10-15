import asyncio
from uuid import UUID

import pytest

from app.application.commands.groups.remove_member.handler import (
    RemoveGroupMemberHandler,
)
from app.application.commands.groups.send_message.handler import SendGroupMessageHandler
from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.dependencies import (
    ProjectionUnavailableError,
    StorageUnavailableError,
)
from app.application.exceptions.groups import GroupReadConflictError
from app.application.ports.persistence.models import (
    GroupMembershipAcceptance,
    GroupMembershipIntent,
    GroupMetadataAcceptance,
    GroupMetadataIntent,
    GroupOwnershipAcceptance,
    GroupOwnershipIntent,
    GroupSnapshot,
)
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.value_objects.message_send_key import MessageSendKey
from app.domain.value_objects.object_id import ObjectId


class ConditionalGroups:
    """Симуляция атомарного порта; не адаптер Cassandra."""

    def __init__(self, group: GroupDialog) -> None:
        self.current = GroupSnapshot(dialog=group, revision=1, last_position=0)
        self.messages: dict[UUID, Message] = {}
        self.receipts: dict[UUID, ReceiptWatermark] = {}
        self.membership_results: dict[tuple[UUID, UUID], GroupMembershipAcceptance] = {}
        self.metadata_results: dict[tuple[UUID, UUID], GroupMetadataAcceptance] = {}
        self.ownership_results: dict[tuple[UUID, UUID], GroupOwnershipAcceptance] = {}
        self.force_conflict: bool = False
        self.lock = asyncio.Lock()
        self.pause_type: type | None = None
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()

    async def get_by_id(self, dialog_id: UUID) -> GroupSnapshot | None:
        if dialog_id != self.current.dialog.id:
            return None
        return GroupSnapshot(
            dialog=self.current.dialog.model_copy(deep=True),
            revision=self.current.revision,
            last_position=self.current.last_position,
        )

    def _require_revision(self, at_revision: int | None) -> None:
        if at_revision is not None and at_revision != self.current.revision:
            raise GroupReadConflictError("Group revision has changed")

    async def get_message(
        self, dialog_id: UUID, message_id: UUID, *, at_revision: int | None = None
    ) -> Message | None:
        self._require_revision(at_revision)
        message = self.messages.get(message_id)
        if message is None or message.dialog_id != dialog_id:
            return None
        return message.model_copy(deep=True)

    async def get_sent_message(
        self,
        dialog_id: UUID,
        send_key: MessageSendKey,
        *,
        at_revision: int | None = None,
    ) -> Message | None:
        self._require_revision(at_revision)
        for message in self.messages.values():
            if message.dialog_id == dialog_id and message.send_key == send_key:
                return message.model_copy(deep=True)
        return None

    async def get_receipt(
        self, dialog_id: UUID, user_id: UUID, *, at_revision: int | None = None
    ) -> ReceiptWatermark | None:
        self._require_revision(at_revision)
        receipt = self.receipts.get(user_id)
        if receipt is None or receipt.dialog_id != dialog_id:
            return None
        return receipt.model_copy(deep=True)

    async def try_commit(
        self,
        expected: GroupSnapshot,
        mutation: GroupDialog | Message | ReceiptWatermark | None,
        *,
        command_id: UUID,
    ) -> bool:
        return await self._try_commit(expected, mutation, command_id=command_id)

    async def get_membership_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ) -> GroupMembershipAcceptance | None:
        self._require_revision(at_revision)
        return self.membership_results.get((dialog_id, command_id))

    async def try_commit_membership(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupMembershipIntent,
    ) -> bool:
        acceptance = GroupMembershipAcceptance(
            intent=intent, result=GroupDialogDTO.from_domain(candidate)
        )
        return await self._try_commit(
            expected, candidate, command_id=command_id, acceptance=acceptance
        )

    async def get_metadata_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ) -> GroupMetadataAcceptance | None:
        self._require_revision(at_revision)
        return self.metadata_results.get((dialog_id, command_id))

    async def try_commit_metadata(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupMetadataIntent,
    ) -> bool:
        acceptance = GroupMetadataAcceptance(
            intent=intent, result=GroupDialogDTO.from_domain(candidate)
        )
        return await self._try_commit(
            expected, candidate, command_id=command_id, metadata_acceptance=acceptance
        )

    async def get_ownership_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ) -> GroupOwnershipAcceptance | None:
        self._require_revision(at_revision)
        return self.ownership_results.get((dialog_id, command_id))

    async def try_commit_ownership(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupOwnershipIntent,
    ) -> bool:
        acceptance = GroupOwnershipAcceptance(
            intent=intent, result=GroupDialogDTO.from_domain(candidate)
        )
        return await self._try_commit(
            expected, candidate, command_id=command_id, ownership_acceptance=acceptance
        )

    async def _try_commit(
        self,
        expected: GroupSnapshot,
        mutation: GroupDialog | Message | ReceiptWatermark | None,
        *,
        command_id: UUID,
        acceptance: GroupMembershipAcceptance | None = None,
        metadata_acceptance: GroupMetadataAcceptance | None = None,
        ownership_acceptance: GroupOwnershipAcceptance | None = None,
    ) -> bool:
        if self.force_conflict:
            return False
        if self.pause_type is not None and isinstance(mutation, self.pause_type):
            self.pause_type = None
            self.entered.set()
            await self.resume.wait()
        async with self.lock:
            if expected.revision != self.current.revision:
                return False
            if acceptance is not None and (
                (expected.dialog.id, command_id) in self.membership_results
                or acceptance.intent.dialog_id != expected.dialog.id
            ):
                return False
            if metadata_acceptance is not None and (
                (expected.dialog.id, command_id) in self.metadata_results
                or metadata_acceptance.intent.dialog_id != expected.dialog.id
            ):
                return False
            if ownership_acceptance is not None and (
                (expected.dialog.id, command_id) in self.ownership_results
                or ownership_acceptance.intent.dialog_id != expected.dialog.id
            ):
                return False
            group = self.current.dialog
            last_position = self.current.last_position
            if isinstance(mutation, GroupDialog):
                group = mutation.model_copy(deep=True)
            elif isinstance(mutation, Message):
                if (
                    mutation.dialog_id != group.id
                    or mutation.id in self.messages
                    or any(
                        saved.send_key == mutation.send_key
                        for saved in self.messages.values()
                    )
                    or mutation.position.value != last_position + 1
                ):
                    return False
                self.messages[mutation.id] = mutation.model_copy(deep=True)
                last_position = mutation.position.value
            elif isinstance(mutation, ReceiptWatermark):
                if mutation.dialog_id != group.id:
                    return False
                saved = self.receipts.get(mutation.user_id)
                if saved is not None:
                    if mutation.id != saved.id or mutation.version != saved.version + 1:
                        return False
                    for candidate, previous in (
                        (mutation.read_through, saved.read_through),
                        (mutation.delivered_through, saved.delivered_through),
                    ):
                        if previous is not None and (
                            candidate is None
                            or candidate.position < previous.position
                            or (
                                candidate.position == previous.position
                                and candidate.message_id != previous.message_id
                            )
                        ):
                            return False
                self.receipts[mutation.user_id] = mutation.model_copy(deep=True)
            self.current = GroupSnapshot(
                dialog=group,
                revision=self.current.revision + 1,
                last_position=last_position,
            )
            if acceptance is not None:
                self.membership_results[(expected.dialog.id, command_id)] = acceptance
            if metadata_acceptance is not None:
                self.metadata_results[(expected.dialog.id, command_id)] = (
                    metadata_acceptance
                )
            if ownership_acceptance is not None:
                self.ownership_results[(expected.dialog.id, command_id)] = (
                    ownership_acceptance
                )
            return True


class ReadyAttachments:
    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        if attachments:
            raise ValueError("This fixture only confirms messages without attachments")


class FakeGroupCreationRepository:
    def __init__(self, groups: dict[UUID, GroupDialog] | None = None) -> None:
        self.groups: dict[UUID, GroupDialog] = groups or {}

    async def create_group(self, group: GroupDialog) -> None:
        self.groups[group.id] = group.model_copy(deep=True)


class FakeAttachmentVerifier:
    def __init__(self, ready_objects: set[ObjectId] | None = None) -> None:
        self.ready_objects = ready_objects or set()
        self.checked: list[tuple[UUID, tuple[ObjectId, ...]]] = []

    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        self.checked.append((sender_id, attachments))
        for item in attachments:
            if item not in self.ready_objects:
                raise StorageUnavailableError(f"Attachment {item} not ready")


class FakeGroupProjections:
    def __init__(self, failing_user_id: UUID | None = None) -> None:
        self.dialogs: dict[tuple[UUID, UUID], GroupDialog] = {}
        self.failing_user_id = failing_user_id
        self.ensured_users: list[UUID] = []

    async def ensure_for_user(self, user_id: UUID, dialog: GroupDialog) -> None:
        if self.failing_user_id is not None and user_id == self.failing_user_id:
            raise ProjectionUnavailableError("Projection unavailable")
        self.ensured_users.append(user_id)
        self.dialogs.setdefault((user_id, dialog.id), dialog)

    def for_user(self, user_id: UUID) -> tuple[GroupDialog, ...]:
        return tuple(
            dialog
            for (owner_id, _), dialog in self.dialogs.items()
            if owner_id == user_id
        )


@pytest.fixture
def charlie_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000003")


@pytest.fixture
def group_projections() -> FakeGroupProjections:
    return FakeGroupProjections()


@pytest.fixture
def group_id() -> UUID:
    return UUID("01995140-0000-7000-8000-000000000900")


@pytest.fixture
def groups(group_id: UUID, alice_id: UUID, bob_id: UUID, clock) -> ConditionalGroups:
    return ConditionalGroups(
        GroupDialog.create(
            dialog_id=group_id,
            title="Рабочая группа",
            owner_id=alice_id,
            initial_members=(bob_id,),
            now=clock.now(),
        )
    )


@pytest.fixture
def send_message(groups, clock, ids) -> SendGroupMessageHandler:
    return SendGroupMessageHandler(
        groups=groups,
        clock=clock.now,
        ids=ids.new_id,
        attachments=ReadyAttachments(),
    )


@pytest.fixture
def remove_member(groups, clock) -> RemoveGroupMemberHandler:
    return RemoveGroupMemberHandler(groups=groups, clock=clock.now)


@pytest.fixture
def make_attachments():
    def _factory(ready_objects: set[ObjectId] | None = None) -> FakeAttachmentVerifier:
        return FakeAttachmentVerifier(ready_objects)

    return _factory


@pytest.fixture
def group_creation_repo() -> FakeGroupCreationRepository:
    return FakeGroupCreationRepository()
