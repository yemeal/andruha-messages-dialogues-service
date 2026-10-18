from enum import StrEnum
from typing import Protocol
from uuid import UUID


class DialogKind(StrEnum):
    DIRECT = "DIRECT"
    GROUP = "GROUP"
    SAVED = "SAVED"


class DialogLookupProtocol(Protocol):
    """Легковесный запрос типа диалога по его ID для маршрутизации команд."""

    async def get_dialog_kind(self, dialog_id: UUID) -> DialogKind | None: ...
