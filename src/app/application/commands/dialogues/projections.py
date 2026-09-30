from uuid import UUID

from app.application.exceptions.dependencies import ProjectionUnavailableError
from app.application.exceptions.dialogues import DialogProjectionsIncompleteError
from app.application.ports.projections.dialogues import DialogProjectionsProtocol
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog


async def ensure_dialog_projections(
    projections: DialogProjectionsProtocol,
    dialog: DirectDialog | SavedDialog,
    users: tuple[UUID, ...],
) -> None:
    for user_id in users:
        try:
            await projections.ensure_for_user(user_id, dialog)
        except ProjectionUnavailableError as error:
            raise DialogProjectionsIncompleteError(dialog.id, user_id) from error
