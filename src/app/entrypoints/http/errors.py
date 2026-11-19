from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.exceptions.dependencies import (
    IdentityUnavailableError,
    ProjectionUnavailableError,
    StorageUnavailableError,
)
from app.application.exceptions.dialogues import (
    DialogProjectionsIncompleteError,
    UserNotRegisteredError,
)
from app.application.exceptions.groups import (
    DialogNotFoundError,
    MessageNotFoundError,
    MessageSendConflictError,
)
from app.domain.exceptions.base import DomainError
from app.domain.exceptions.dialogues import NotDialogParticipantError
from app.infrastructure.bootstrap.messaging import AttachmentsUnavailableError
from app.infrastructure.security.cursors import ExpiredCursorError, InvalidCursorError


def install_errors(app: FastAPI) -> None:
    async def map_error(request: Request, error: Exception) -> JSONResponse:
        code, detail, status = "invalid_request", "invalid request", 422
        if isinstance(
            error,
            (
                StorageUnavailableError,
                IdentityUnavailableError,
                ProjectionUnavailableError,
                DialogProjectionsIncompleteError,
            ),
        ):
            code, detail, status = (
                "temporarily_unavailable",
                "retry the same operation",
                503,
            )
        elif isinstance(
            error,
            (DialogNotFoundError, MessageNotFoundError, NotDialogParticipantError),
        ):
            code, detail, status = "not_found", "resource not found", 404
        elif isinstance(error, MessageSendConflictError):
            code, detail, status = "send_conflict", "send identity already used", 409
        elif isinstance(error, UserNotRegisteredError):
            code, detail, status = (
                "user_not_registered",
                "registration is not completed",
                409,
            )
        elif isinstance(error, ExpiredCursorError):
            code, detail, status = (
                "full_resync_required",
                "cursor expired; request a new snapshot",
                410,
            )
        elif isinstance(error, InvalidCursorError):
            code, detail, status = "invalid_cursor", "invalid cursor", 400
        elif isinstance(error, AttachmentsUnavailableError):
            code, detail, status = "media_not_available", "media is not enabled", 503
        content = {"code": code, "detail": detail}
        if isinstance(error, DialogProjectionsIncompleteError):
            content["dialogId"] = str(error.dialog_id)
        return JSONResponse(
            content,
            status_code=status,
            headers={
                "Cache-Control": "no-store",
                **({"Retry-After": "1"} if status == 503 else {}),
            },
        )

    for error_type in (
        StorageUnavailableError,
        IdentityUnavailableError,
        ProjectionUnavailableError,
        DialogProjectionsIncompleteError,
        DialogNotFoundError,
        MessageNotFoundError,
        MessageSendConflictError,
        UserNotRegisteredError,
        DomainError,
        InvalidCursorError,
        AttachmentsUnavailableError,
        RequestValidationError,
    ):
        app.add_exception_handler(error_type, map_error)
