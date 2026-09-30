from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.exceptions.dialogues import UserNotRegisteredError
from app.application.ports.persistence.models import CanonicalDialog
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.direct_participants import DirectParticipants


class RegisteredUsers:
    def __init__(self, users: frozenset[UUID]) -> None:
        self.users = users

    async def require_registered(self, user_id: UUID) -> None:
        if user_id not in self.users:
            raise UserNotRegisteredError(user_id)


class DirectDialogs:
    def __init__(self) -> None:
        self.dialogs: dict[DirectParticipants, DirectDialog] = {}

    async def get_by_participants(
        self, participants: DirectParticipants
    ) -> DirectDialog | None:
        return self.dialogs.get(participants)

    async def create_or_get(
        self, candidate: DirectDialog
    ) -> CanonicalDialog[DirectDialog]:
        existing = self.dialogs.get(candidate.participants)
        if existing is not None:
            return CanonicalDialog(dialog=existing, created=False)
        self.dialogs[candidate.participants] = candidate
        return CanonicalDialog(dialog=candidate, created=True)


class SavedDialogs:
    def __init__(self) -> None:
        self.dialogs: dict[UUID, SavedDialog] = {}

    async def get_by_owner(self, user_id: UUID) -> SavedDialog | None:
        return self.dialogs.get(user_id)

    async def create_or_get(
        self, candidate: SavedDialog
    ) -> CanonicalDialog[SavedDialog]:
        existing = self.dialogs.get(candidate.user_id)
        if existing is not None:
            return CanonicalDialog(dialog=existing, created=False)
        self.dialogs[candidate.user_id] = candidate
        return CanonicalDialog(dialog=candidate, created=True)


class DialogProjections:
    def __init__(self) -> None:
        self.dialogs: dict[tuple[UUID, UUID], DirectDialog | SavedDialog] = {}

    async def ensure_for_user(
        self, user_id: UUID, dialog: DirectDialog | SavedDialog
    ) -> None:
        self.dialogs.setdefault((user_id, dialog.id), dialog)

    def for_user(self, user_id: UUID) -> tuple[DirectDialog | SavedDialog, ...]:
        return tuple(
            dialog
            for (owner_id, _), dialog in self.dialogs.items()
            if owner_id == user_id
        )


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 30, 5, tzinfo=UTC)


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> UUID:
        self.value += 1
        return UUID(f"01995140-0000-7000-8000-{self.value:012x}")


@pytest.fixture
def alice_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def bob_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def direct_dialogs() -> DirectDialogs:
    return DirectDialogs()


@pytest.fixture
def saved_dialogs() -> SavedDialogs:
    return SavedDialogs()


@pytest.fixture
def projections() -> DialogProjections:
    return DialogProjections()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def ids() -> SequentialIds:
    return SequentialIds()


@pytest.fixture
def registered_users(alice_id: UUID, bob_id: UUID) -> RegisteredUsers:
    return RegisteredUsers(frozenset((alice_id, bob_id)))
