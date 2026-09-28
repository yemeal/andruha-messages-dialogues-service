from datetime import datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain import GroupDialog, ObjectId
from app.domain.exceptions import InvalidDomainTimestampError, NotGroupMemberError


def test_member_can_set_replace_and_remove_group_avatar(
    alice_id: UUID, bob_id: UUID, now: datetime
) -> None:
    group = GroupDialog.create(
        title="Team", owner_id=alice_id, initial_members=(bob_id,), now=now
    )
    first = ObjectId.from_uuid(UUID("01995140-0000-7000-8000-000000000020"))
    second = ObjectId.from_uuid(UUID("01995140-0000-7000-8000-000000000021"))

    assert group.avatar_object_id is None
    assert group.change_avatar(first, now + timedelta(seconds=1), actor_id=bob_id)
    assert group.avatar_object_id == first
    assert group.version == 2
    assert group.change_avatar(second, now + timedelta(seconds=2), actor_id=alice_id)
    assert group.avatar_object_id == second
    assert group.version == 3
    assert group.remove_avatar(now + timedelta(seconds=3), actor_id=bob_id)
    assert group.avatar_object_id is None
    assert group.version == 4


def test_creation_and_restoration_preserve_an_initial_avatar(
    alice_id: UUID, now: datetime
) -> None:
    reference = ObjectId.from_uuid(UUID("01995140-0000-7000-8000-000000000020"))
    group = GroupDialog.create(
        title="Team", owner_id=alice_id, avatar_object_id=reference, now=now
    )
    snapshot = group.model_dump(mode="json")

    assert snapshot["avatar_object_id"] == str(reference)
    assert GroupDialog.model_validate_json(group.model_dump_json()) == group
    assert group.version == 1


def test_avatar_repeats_and_rejections_preserve_the_entire_group(
    alice_id: UUID, outsider_id: UUID, now: datetime
) -> None:
    reference = ObjectId.from_uuid(UUID("01995140-0000-7000-8000-000000000020"))
    replacement = ObjectId.from_uuid(UUID("01995140-0000-7000-8000-000000000021"))
    group = GroupDialog.create(title="Team", owner_id=alice_id, now=now)
    assert not group.remove_avatar(now, actor_id=alice_id)
    group.change_avatar(reference, now + timedelta(seconds=1), actor_id=alice_id)
    before = group.model_dump()

    assert not group.change_avatar(
        reference, now + timedelta(seconds=2), actor_id=alice_id
    )
    with pytest.raises(NotGroupMemberError):
        group.change_avatar(reference, now, actor_id=outsider_id)
    with pytest.raises(NotGroupMemberError):
        group.remove_avatar(now, actor_id=outsider_id)
    with pytest.raises(InvalidDomainTimestampError):
        group.change_avatar(replacement, now - timedelta(seconds=1), actor_id=alice_id)
    with pytest.raises(ValidationError):
        group.change_avatar(
            "https://storage.example/avatar.jpg", now, actor_id=alice_id
        )

    assert group.model_dump() == before
