from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.application.dto.groups import GroupDialogDTO
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.group_title import GroupTitle
from app.domain.value_objects.object_id import ObjectId


@dataclass(frozen=True)
class CanonicalDialog[T: DirectDialog | SavedDialog]:
    dialog: T
    created: bool


@dataclass(frozen=True)
class GroupSnapshot:
    """Изолированный снимок агрегата и ревизии атомарного принятия команд."""

    dialog: GroupDialog
    revision: int
    last_position: int


type GroupMutation = GroupDialog | Message | ReceiptWatermark | None


class MembershipAction(StrEnum):
    ADD = "ADD"
    REMOVE = "REMOVE"


@dataclass(frozen=True)
class GroupMembershipIntent:
    dialog_id: UUID
    actor_id: UUID
    user_id: UUID
    action: MembershipAction


@dataclass(frozen=True)
class GroupMembershipAcceptance:
    """Неизменяемые намерение и результат одной принятой команды состава."""

    intent: GroupMembershipIntent
    result: GroupDialogDTO


class MetadataAction(StrEnum):
    RENAME = "RENAME"
    CHANGE_AVATAR = "CHANGE_AVATAR"
    REMOVE_AVATAR = "REMOVE_AVATAR"


@dataclass(frozen=True)
class GroupMetadataIntent:
    dialog_id: UUID
    actor_id: UUID
    action: MetadataAction
    title: GroupTitle | None = None
    avatar_object_id: ObjectId | None = None

    def __post_init__(self) -> None:
        if self.action == MetadataAction.RENAME:
            if self.title is None or self.avatar_object_id is not None:
                raise ValueError("RENAME intent requires title and no avatar_object_id")
        elif self.action == MetadataAction.CHANGE_AVATAR:
            if self.avatar_object_id is None or self.title is not None:
                raise ValueError(
                    "CHANGE_AVATAR intent requires avatar_object_id and no title"
                )
        elif self.action == MetadataAction.REMOVE_AVATAR and (
            self.title is not None or self.avatar_object_id is not None
        ):
            raise ValueError(
                "REMOVE_AVATAR intent must not have title or avatar_object_id"
            )


@dataclass(frozen=True)
class GroupMetadataAcceptance:
    """Неизменяемые намерение и результат одной принятой команды метаданных."""

    intent: GroupMetadataIntent
    result: GroupDialogDTO


@dataclass(frozen=True)
class GroupOwnershipIntent:
    dialog_id: UUID
    actor_id: UUID
    new_owner_id: UUID


@dataclass(frozen=True)
class GroupOwnershipAcceptance:
    """Неизменяемые намерение и результат одной принятой команды передачи владения."""

    intent: GroupOwnershipIntent
    result: GroupDialogDTO
