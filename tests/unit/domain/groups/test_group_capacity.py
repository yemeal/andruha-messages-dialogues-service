from datetime import datetime
from uuid import UUID

import pytest

from app.domain import GroupDialog


def test_group_limit_includes_owner_and_is_enforced_on_every_state_boundary(
    alice_id: UUID, outsider_id: UUID, now: datetime
) -> None:
    from app.domain.exceptions.groups import GroupMemberLimitExceededError

    members = tuple(UUID(int=i) for i in range(1, 1000))
    group = GroupDialog.create(
        title="Full", owner_id=alice_id, initial_members=members, now=now
    )
    before = group.model_dump()

    assert group.member_count == 1000
    with pytest.raises(GroupMemberLimitExceededError):
        group.add_member(outsider_id, now, actor_id=alice_id)
    assert group.model_dump() == before

    with pytest.raises(GroupMemberLimitExceededError):
        GroupDialog.create(
            title="Overflow",
            owner_id=alice_id,
            initial_members=(*members, outsider_id),
            now=now,
        )
    with pytest.raises(GroupMemberLimitExceededError):
        GroupDialog.model_validate({**before, "members": (*group.members, outsider_id)})
