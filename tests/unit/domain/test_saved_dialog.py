from uuid import uuid7

import pytest
from pydantic import ValidationError

from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.clock import utc_now
from app.domain.exceptions.dialogues import NotDialogParticipantError


def test_create_saved_dialog() -> None:
    user_id = uuid7()
    t0 = utc_now()
    dialog_id = uuid7()

    dialog = SavedDialog.create(
        user_id=user_id,
        dialog_id=dialog_id,
        now=t0,
    )

    assert dialog.id == dialog_id
    assert dialog.user_id == user_id
    assert dialog.created_at == t0


def test_create_saved_dialog_defaults() -> None:
    user_id = uuid7()
    dialog = SavedDialog.create(user_id=user_id)

    assert dialog.id.version == 7
    assert dialog.user_id == user_id


def test_membership_and_peer_of() -> None:
    user_id = uuid7()
    outsider = uuid7()
    dialog = SavedDialog.create(user_id=user_id)

    assert user_id in dialog
    assert outsider not in dialog

    assert dialog.peer_of(user_id) == user_id

    with pytest.raises(NotDialogParticipantError):
        dialog.peer_of(outsider)


def test_immutability() -> None:
    user_id = uuid7()
    dialog = SavedDialog.create(user_id=user_id)

    with pytest.raises(ValidationError):
        dialog.user_id = uuid7()  # type: ignore[misc]
