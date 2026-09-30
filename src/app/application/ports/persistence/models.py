from dataclasses import dataclass

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
