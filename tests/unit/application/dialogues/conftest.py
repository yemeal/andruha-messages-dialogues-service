import pytest

from app.application.commands.dialogues.create_direct.handler import (
    CreateDirectDialogHandler,
)
from app.application.commands.dialogues.create_saved.handler import (
    CreateSavedDialogHandler,
)


@pytest.fixture
def direct_creation(
    direct_dialogs,
    projections,
    registered_users,
    clock,
    ids,
) -> CreateDirectDialogHandler:
    return CreateDirectDialogHandler(
        direct_dialogs=direct_dialogs,
        projections=projections,
        registered_users=registered_users,
        clock=clock.now,
        ids=ids.new_id,
    )


@pytest.fixture
def saved_creation(
    saved_dialogs, projections, registered_users, clock, ids
) -> CreateSavedDialogHandler:
    return CreateSavedDialogHandler(
        saved_dialogs=saved_dialogs,
        projections=projections,
        registered_users=registered_users,
        clock=clock.now,
        ids=ids.new_id,
    )
