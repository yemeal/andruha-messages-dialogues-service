from datetime import timedelta
from uuid import uuid7

import pytest
from pydantic import ValidationError

from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.clock import utc_now
from app.domain.exceptions.groups import (
    CannotRemoveOwnerError,
    EmptyGroupMembersError,
    GroupMemberAlreadyExistsError,
    NotGroupMemberError,
)
from app.domain.value_objects.group_title import GroupTitle


def test_create_group_dialog_defaults() -> None:
    owner_id = uuid7()
    t0 = utc_now()
    group = GroupDialog.create(title="Engineering", owner_id=owner_id, now=t0)

    assert group.title.value == "Engineering"
    assert group.owner_id == owner_id
    assert owner_id in group
    assert group.member_count == 1
    assert group.version == 1
    assert group.created_at == t0
    assert group.updated_at == t0


def test_create_group_dialog_with_initial_members() -> None:
    owner = uuid7()
    u1 = uuid7()
    u2 = uuid7()
    group = GroupDialog.create(
        title=GroupTitle.from_str("Core"),
        owner_id=owner,
        initial_members=[u1, u2],
    )

    assert group.member_count == 3
    assert owner in group
    assert u1 in group
    assert u2 in group


def test_add_member() -> None:
    owner = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner)
    new_user = uuid7()
    t1 = utc_now() + timedelta(seconds=1)

    changed = group.add_member(new_user, now=t1)
    assert changed is True
    assert new_user in group
    assert group.member_count == 2
    assert group.version == 2
    assert group.updated_at == t1


def test_add_existing_member_raises_error() -> None:
    owner = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner)

    with pytest.raises(GroupMemberAlreadyExistsError):
        group.add_member(owner, now=utc_now())


def test_remove_member() -> None:
    owner = uuid7()
    u1 = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner, initial_members=[u1])
    t1 = utc_now() + timedelta(seconds=1)

    changed = group.remove_member(u1, now=t1)
    assert changed is True
    assert u1 not in group
    assert group.member_count == 1
    assert group.version == 2
    assert group.updated_at == t1


def test_cannot_remove_owner() -> None:
    owner = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner)

    with pytest.raises(CannotRemoveOwnerError):
        group.remove_member(owner, now=utc_now())


def test_cannot_remove_non_member() -> None:
    owner = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner)
    outsider = uuid7()

    with pytest.raises(NotGroupMemberError):
        group.remove_member(outsider, now=utc_now())


def test_rename() -> None:
    owner = uuid7()
    group = GroupDialog.create(title="Old Name", owner_id=owner)
    t1 = utc_now() + timedelta(seconds=1)

    changed = group.rename("New Name", now=t1)
    assert changed is True
    assert group.title.value == "New Name"
    assert group.version == 2
    assert group.updated_at == t1

    # Rename with same name is a no-op
    t2 = t1 + timedelta(seconds=1)
    changed_again = group.rename("New Name", now=t2)
    assert changed_again is False
    assert group.version == 2
    assert group.updated_at == t1


def test_change_owner() -> None:
    owner = uuid7()
    u1 = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner, initial_members=[u1])
    t1 = utc_now() + timedelta(seconds=1)

    changed = group.change_owner(u1, now=t1)
    assert changed is True
    assert group.owner_id == u1
    assert group.version == 2

    # Cannot transfer ownership to outsider
    outsider = uuid7()
    with pytest.raises(NotGroupMemberError):
        group.change_owner(outsider, now=t1 + timedelta(seconds=1))


def test_direct_hydration_invariants() -> None:
    owner = uuid7()
    outsider = uuid7()
    t0 = utc_now()

    # Owner must be in members
    with pytest.raises(CannotRemoveOwnerError):
        GroupDialog(
            id=uuid7(),
            title=GroupTitle.from_str("Test"),
            owner_id=owner,
            members=frozenset([outsider]),
            created_at=t0,
            updated_at=t0,
            version=1,
        )

    # Members cannot be empty
    with pytest.raises(EmptyGroupMembersError):
        GroupDialog(
            id=uuid7(),
            title=GroupTitle.from_str("Test"),
            owner_id=owner,
            members=frozenset(),
            created_at=t0,
            updated_at=t0,
            version=1,
        )


def test_immutability() -> None:
    owner = uuid7()
    group = GroupDialog.create(title="Devs", owner_id=owner)

    with pytest.raises(ValidationError):
        group.owner_id = uuid7()  # type: ignore[misc]

    with pytest.raises(ValidationError):
        group.title = GroupTitle.from_str("Hacked")  # type: ignore[misc]


def test_direct_construction_with_string_and_list() -> None:
    owner = uuid7()
    t0 = utc_now()
    group = GroupDialog(
        id=uuid7(),
        title="Direct String",  # type: ignore[arg-type]
        owner_id=owner,
        members=[owner],  # type: ignore[arg-type]
        created_at=t0,
        updated_at=t0,
        version=1,
    )
    assert group.title.value == "Direct String"
    assert isinstance(group.members, frozenset)


def test_rejects_invalid_types_for_title_and_members() -> None:
    owner = uuid7()
    t0 = utc_now()
    with pytest.raises(ValidationError):
        GroupDialog(
            id=uuid7(),
            title=123,  # type: ignore[arg-type]
            owner_id=owner,
            members=[owner],  # type: ignore[arg-type]
            created_at=t0,
            updated_at=t0,
            version=1,
        )

    with pytest.raises(ValidationError):
        GroupDialog(
            id=uuid7(),
            title="Valid",  # type: ignore[arg-type]
            owner_id=owner,
            members=123,  # type: ignore[arg-type]
            created_at=t0,
            updated_at=t0,
            version=1,
        )
