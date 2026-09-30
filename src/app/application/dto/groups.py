from datetime import datetime
from typing import Self
from uuid import UUID

from app.application.dto.base import BaseDTO
from app.domain.aggregates.group_dialog import GroupDialog


class GroupDialogDTO(BaseDTO):
    id: UUID
    title: str
    owner_id: UUID
    members: tuple[UUID, ...]
    avatar_object_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime | None

    @classmethod
    def from_domain(cls, group: GroupDialog) -> Self:
        return cls(
            id=group.id,
            title=group.title.value,
            owner_id=group.owner_id,
            members=tuple(sorted(group.members)),
            avatar_object_id=(
                group.avatar_object_id.value
                if group.avatar_object_id is not None
                else None
            ),
            version=group.version,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
