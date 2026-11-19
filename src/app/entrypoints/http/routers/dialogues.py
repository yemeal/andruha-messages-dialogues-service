"""Versioned text messaging API; the actor always comes from the verified JWT."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.application.commands.dialogues.create_direct.command import (
    CreateDirectDialogCommand,
)
from app.application.commands.dialogues.create_saved.command import (
    CreateSavedDialogCommand,
)
from app.application.commands.dialogues.send_direct_message.command import (
    SendDirectMessageCommand,
)
from app.application.commands.dialogues.send_saved_message.command import (
    SendSavedMessageCommand,
)
from app.application.dto.messages import MessageDTO
from app.application.dto.reading import DialogSummary
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.limits import MAX_MESSAGE_TEXT_LENGTH
from app.infrastructure.bootstrap.messaging import MessagingRuntime
from app.infrastructure.persistence.cassandra.limits import MAX_PAGE_SIZE
from app.infrastructure.security.access_tokens import InvalidAccessTokenError

router = APIRouter(prefix="/api/v1/dialogues", tags=["dialogues"])


class HTTPModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class CreateDirectRequest(HTTPModel):
    peer_id: UUID


class SendTextRequest(HTTPModel):
    client_message_id: UUID
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_TEXT_LENGTH)


class MessageResponse(HTTPModel):
    message_id: UUID
    dialog_id: UUID
    sender_id: UUID
    client_message_id: UUID
    text: str | None
    attachment_ids: tuple[UUID, ...]
    position: int
    version: int
    sent_at: datetime
    edited_at: datetime | None
    is_edited: bool

    @classmethod
    def from_dto(cls, message: MessageDTO) -> Self:
        return cls(
            message_id=message.id,
            dialog_id=message.dialog_id,
            sender_id=message.sender_id,
            client_message_id=message.client_message_id,
            text=message.text,
            attachment_ids=message.attachment_ids,
            position=message.position,
            version=message.version,
            sent_at=message.created_at,
            edited_at=message.edited_at,
            is_edited=message.is_edited,
        )


class DialogResponse(HTTPModel):
    dialog_id: UUID
    kind: str
    participant_ids: tuple[UUID, ...]
    created_at: datetime
    last_position: int
    last_message: MessageResponse | None = Field(default=None)

    @classmethod
    def from_dto(cls, dialog: DialogSummary) -> Self:
        return cls(
            dialog_id=dialog.id,
            kind=dialog.kind,
            participant_ids=dialog.participant_ids,
            created_at=dialog.created_at,
            last_position=dialog.last_position,
            last_message=MessageResponse.from_dto(dialog.last_message)
            if dialog.last_message
            else None,
        )


class CreatedResponse(HTTPModel):
    dialog: DialogResponse
    created: bool


class SentResponse(HTTPModel):
    message: MessageResponse


class HistoryResponse(HTTPModel):
    items: tuple[MessageResponse, ...]
    next_cursor: str | None


class DialogsResponse(HTTPModel):
    items: tuple[DialogResponse, ...]
    next_cursor: str | None


class SyncResponseEntry(HTTPModel):
    sequence: int
    event_id: UUID
    type: str
    dialog_id: UUID
    message: MessageResponse | None


class SyncResponse(HTTPModel):
    items: tuple[SyncResponseEntry, ...]
    cursor: str
    has_more: bool


def get_runtime(request: Request) -> MessagingRuntime:
    runtime = getattr(request.app.state, "messaging_runtime", None)
    if not isinstance(runtime, MessagingRuntime):
        raise HTTPException(503, "messaging role is not enabled")
    return runtime


Runtime = Annotated[MessagingRuntime, Depends(get_runtime)]


def get_actor(
    runtime: Runtime, authorization: Annotated[str | None, Header()] = None
) -> UUID:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            401, "invalid access token", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return runtime.verifier.verify(authorization[7:])
    except InvalidAccessTokenError as error:
        raise HTTPException(
            401, "invalid access token", headers={"WWW-Authenticate": "Bearer"}
        ) from error


Actor = Annotated[UUID, Depends(get_actor)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Cursor = Annotated[str | None, Query(max_length=2048)]


@router.post("/direct", response_model=CreatedResponse)
async def create_direct(
    body: CreateDirectRequest, actor: Actor, runtime: Runtime, response: Response
) -> CreatedResponse:
    result = await runtime.create_direct(
        CreateDirectDialogCommand(actor_id=actor, peer_id=body.peer_id)
    )
    response.status_code = 201 if result.created else 200
    dialog = await runtime.queries.detail(actor, result.dialog.id)
    return CreatedResponse(
        dialog=DialogResponse.from_dto(dialog), created=result.created
    )


@router.post("/saved", response_model=CreatedResponse)
async def create_saved(
    actor: Actor, runtime: Runtime, response: Response
) -> CreatedResponse:
    result = await runtime.create_saved(CreateSavedDialogCommand(actor_id=actor))
    response.status_code = 201 if result.created else 200
    dialog = await runtime.queries.detail(actor, result.dialog.id)
    return CreatedResponse(
        dialog=DialogResponse.from_dto(dialog), created=result.created
    )


@router.get("/sync", response_model=SyncResponse)
async def sync(
    actor: Actor,
    runtime: Runtime,
    response: Response,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> SyncResponse:
    response.headers["Cache-Control"] = "no-store"
    decoded = (
        runtime.cursors.decode(cursor, actor, "sync:sequence:asc") if cursor else None
    )
    batch = await runtime.views.sync(
        actor,
        after=decoded.after if decoded else 0,
        through=decoded.through if decoded else None,
        limit=limit,
    )
    after = (
        batch.items[-1].sequence if batch.items else (decoded.after if decoded else 0)
    )
    more = after < batch.through
    return SyncResponse(
        items=tuple(
            SyncResponseEntry(
                sequence=item.sequence,
                event_id=item.event_id,
                type=item.type,
                dialog_id=item.dialog_id,
                message=MessageResponse.from_dto(item.message)
                if item.message
                else None,
            )
            for item in batch.items
        ),
        cursor=runtime.cursors.encode(
            actor,
            "sync:sequence:asc",
            after=after,
            through=batch.through if more else None,
        ),
        has_more=more,
    )


@router.get("/", response_model=DialogsResponse)
async def dialogs(
    actor: Actor, runtime: Runtime, cursor: Cursor = None, limit: Limit = 50
) -> DialogsResponse:
    decoded = (
        runtime.cursors.decode(cursor, actor, "dialogs:created:asc") if cursor else None
    )
    batch = await runtime.views.dialogs(
        actor,
        after=decoded.after if decoded else 0,
        through=decoded.through if decoded else None,
        limit=limit,
    )
    more = batch.through < batch.upper
    return DialogsResponse(
        items=tuple(DialogResponse.from_dto(item) for item in batch.items),
        next_cursor=runtime.cursors.encode(
            actor, "dialogs:created:asc", after=batch.through, through=batch.upper
        )
        if more
        else None,
    )


@router.get("/{dialog_id}", response_model=DialogResponse)
async def dialog(dialog_id: UUID, actor: Actor, runtime: Runtime) -> DialogResponse:
    value = await runtime.queries.detail(actor, dialog_id)
    return DialogResponse.from_dto(value)


@router.post("/{dialog_id}/messages", response_model=SentResponse)
async def send(
    dialog_id: UUID, body: SendTextRequest, actor: Actor, runtime: Runtime
) -> SentResponse:
    value = await runtime.queries.require_dialog(actor, dialog_id)
    if isinstance(value, DirectDialog):
        result = await runtime.send_direct(
            SendDirectMessageCommand(
                dialog_id=dialog_id,
                actor_id=actor,
                client_message_id=body.client_message_id,
                text=body.text,
            )
        )
    else:
        result = await runtime.send_saved(
            SendSavedMessageCommand(
                dialog_id=dialog_id,
                actor_id=actor,
                client_message_id=body.client_message_id,
                text=body.text,
            )
        )
    return SentResponse(message=MessageResponse.from_dto(result.message))


@router.get("/{dialog_id}/messages", response_model=HistoryResponse)
async def history(
    dialog_id: UUID,
    actor: Actor,
    runtime: Runtime,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> HistoryResponse:
    scope = f"history:{dialog_id}:position:asc"
    decoded = runtime.cursors.decode(cursor, actor, scope) if cursor else None
    items, upper = await runtime.queries.history(
        actor,
        dialog_id,
        after=decoded.after if decoded else 0,
        through=decoded.through if decoded else None,
        limit=limit,
    )
    after = items[-1].position if items else (decoded.after if decoded else 0)
    return HistoryResponse(
        items=tuple(MessageResponse.from_dto(item) for item in items),
        next_cursor=runtime.cursors.encode(actor, scope, after=after, through=upper)
        if after < upper
        else None,
    )


@router.get("/{dialog_id}/messages/{message_id}", response_model=MessageResponse)
async def message(
    dialog_id: UUID, message_id: UUID, actor: Actor, runtime: Runtime
) -> MessageResponse:
    return MessageResponse.from_dto(
        await runtime.queries.point(actor, dialog_id, message_id)
    )
