from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.application.dto.groups import GroupDialogDTO
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.group_dialog import GroupDialog
from app.domain.aggregates.message import Message
from app.domain.aggregates.receipt_watermark import ReceiptWatermark
from app.domain.aggregates.saved_dialog import SavedDialog


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
