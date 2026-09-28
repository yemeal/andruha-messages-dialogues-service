from datetime import datetime, timedelta
from uuid import UUID, uuid7

import pytest

from app.domain import GroupDialog
from app.domain.exceptions.groups import NotGroupMemberError, NotGroupOwnerError


def test_nonmember_cannot_rename_group(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Original", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    before = group.model_dump()

    with pytest.raises(NotGroupMemberError):
        group.rename("Changed", now + timedelta(seconds=1), actor_id=uuid7())

    assert group.model_dump() == before


def test_member_other_than_owner_can_rename_group(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Original", owner_id=alice_id, initial_members=(bob_id,), now=now
    )

    assert group.rename("Changed", now + timedelta(seconds=1), actor_id=bob_id)
    assert group.title.value == "Changed"


def test_nonmember_cannot_add_group_member(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(title="Group", owner_id=alice_id, now=now)
    before = group.model_dump()

    with pytest.raises(NotGroupMemberError):
        group.add_member(bob_id, now + timedelta(seconds=1), actor_id=uuid7())

    assert group.model_dump() == before


def test_nonmember_cannot_remove_group_member(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Group", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    before = group.model_dump()

    with pytest.raises(NotGroupMemberError):
        group.remove_member(bob_id, now + timedelta(seconds=1), actor_id=uuid7())

    assert group.model_dump() == before


def test_member_other_than_owner_can_manage_members(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Group", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    newcomer = uuid7()

    assert group.add_member(newcomer, now + timedelta(seconds=1), actor_id=bob_id)
    assert newcomer in group
    assert group.remove_member(newcomer, now + timedelta(seconds=2), actor_id=bob_id)
    assert newcomer not in group


def test_only_current_owner_can_transfer_ownership(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Group", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    before = group.model_dump()

    with pytest.raises(NotGroupOwnerError):
        group.change_owner(bob_id, now + timedelta(seconds=1), actor_id=bob_id)

    assert group.model_dump() == before


def test_previous_owner_loses_transfer_right_after_handoff(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Group", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    group.change_owner(bob_id, now + timedelta(seconds=1), actor_id=alice_id)
    before = group.model_dump()

    with pytest.raises(NotGroupOwnerError):
        group.change_owner(alice_id, now + timedelta(seconds=2), actor_id=alice_id)

    assert group.model_dump() == before
    assert group.change_owner(alice_id, now + timedelta(seconds=2), actor_id=bob_id)
