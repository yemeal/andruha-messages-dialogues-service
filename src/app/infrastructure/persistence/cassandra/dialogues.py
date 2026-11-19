"""Unique immutable dialogue creation and recoverable canonical-by-ID records."""

from collections.abc import Callable
from contextlib import suppress
from uuid import UUID

from cassandra.cluster import Session
from pydantic import BaseModel, ValidationError

from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.ports.persistence.models import CanonicalDialog
from app.domain.aggregates.direct_dialog import DirectDialog
from app.domain.aggregates.saved_dialog import SavedDialog
from app.domain.value_objects.direct_participants import DirectParticipants
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.statements import (
    DRIVER_ERRORS,
    conditional_write,
    serial_read,
)


class _Creation(BaseModel):
    dialog_id: UUID
    dialog_kind: str
    payload: str


class _Head(BaseModel):
    command_kind: str | None
    payload: str


def _direct_key(participants: DirectParticipants) -> str:
    return f"direct:{participants.first}:{participants.second}"


class _UniqueDialogs[T: DirectDialog | SavedDialog]:
    def __init__(
        self,
        session: Session | AsyncCassandraSession,
        *,
        model: type[T],
        kind: str,
        identity: Callable[[T], str],
        timeout_seconds: float,
    ) -> None:
        self._session = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )
        self._timeout = timeout_seconds
        self._model = model
        self._kind = kind
        self._identity = identity

    async def _creation(self, key: str) -> _Creation | None:
        result = await self._session.execute(
            serial_read(
                "SELECT dialog_id, dialog_kind, payload FROM dialog_creations "
                "WHERE creation_key=%s"
            ),
            (key,),
            timeout=self._timeout,
        )
        row = result.one()
        return (
            _Creation.model_validate(row, from_attributes=True)
            if row is not None
            else None
        )

    async def _head(self, dialog_id: UUID) -> _Head | None:
        result = await self._session.execute(
            serial_read(
                "SELECT command_kind, payload FROM canonical_rows "
                "WHERE dialog_id=%s AND row_key='state'"
            ),
            (dialog_id,),
            timeout=self._timeout,
        )
        row = result.one()
        return (
            _Head.model_validate(row, from_attributes=True) if row is not None else None
        )

    async def _materialize(self, dialog: T) -> None:
        # Confirm the durable row even when the INSERT response is unknown.
        with suppress(*DRIVER_ERRORS):
            await self._session.execute(
                conditional_write(
                    "INSERT INTO canonical_rows "
                    "(dialog_id, row_key, revision, last_position, pending_count, "
                    "payload, command_kind, intent, result) "
                    "VALUES (%s, 'state', 1, 0, 0, %s, %s, '{}', %s) IF NOT EXISTS"
                ),
                (
                    dialog.id,
                    dialog.model_dump_json(),
                    self._kind,
                    dialog.model_dump_json(),
                ),
                timeout=self._timeout,
            )
        head = await self._head(dialog.id)
        if (
            head is None
            or head.command_kind != self._kind
            or (self._model.model_validate_json(head.payload) != dialog)
        ):
            raise StorageUnavailableError("Canonical dialog was not confirmed")

    async def _restore(self, record: _Creation, key: str) -> T:
        dialog = self._model.model_validate_json(record.payload)
        if (
            record.dialog_kind != self._kind
            or dialog.id != record.dialog_id
            or self._identity(dialog) != key
        ):
            raise StorageUnavailableError("Dialog creation record is inconsistent")
        await self._materialize(dialog)
        return dialog

    async def _get_by_key(self, key: str) -> T | None:
        async def read() -> T | None:
            record = await self._creation(key)
            return await self._restore(record, key) if record is not None else None

        try:
            return await read()
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError("Dialog creation read unavailable") from error

    async def get_by_id(self, dialog_id: UUID) -> T | None:
        async def read() -> T | None:
            head = await self._head(dialog_id)
            if head is None or head.command_kind != self._kind:
                return None
            dialog = self._model.model_validate_json(head.payload)
            if dialog.id != dialog_id:
                raise StorageUnavailableError(
                    "Canonical dialog identity is inconsistent"
                )
            return dialog

        try:
            return await read()
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError(
                "Canonical dialog read unavailable"
            ) from error

    async def create_or_get(self, candidate: T) -> CanonicalDialog[T]:
        async def create() -> CanonicalDialog[T]:
            created = False
            with suppress(*DRIVER_ERRORS):
                result = await self._session.execute(
                    conditional_write(
                        "INSERT INTO dialog_creations "
                        "(creation_key, dialog_id, dialog_kind, payload) "
                        "VALUES (%s, %s, %s, %s) IF NOT EXISTS"
                    ),
                    (
                        self._identity(candidate),
                        candidate.id,
                        self._kind,
                        candidate.model_dump_json(),
                    ),
                    timeout=self._timeout,
                )
                created = result.was_applied
            record = await self._creation(self._identity(candidate))
            if record is None:
                raise StorageUnavailableError("Dialog creation outcome is unknown")
            return CanonicalDialog(
                await self._restore(record, self._identity(candidate)), created=created
            )

        try:
            return await create()
        except (*DRIVER_ERRORS, ValidationError) as error:
            raise StorageUnavailableError("Dialog creation unavailable") from error


class CassandraDirectDialogs(_UniqueDialogs[DirectDialog]):
    def __init__(
        self, session: Session | AsyncCassandraSession, *, timeout_seconds: float = 5
    ) -> None:
        super().__init__(
            session,
            model=DirectDialog,
            kind="DIRECT",
            timeout_seconds=timeout_seconds,
            identity=lambda dialog: _direct_key(dialog.participants),
        )

    async def get_by_participants(
        self, participants: DirectParticipants
    ) -> DirectDialog | None:
        return await self._get_by_key(_direct_key(participants))


class CassandraSavedDialogs(_UniqueDialogs[SavedDialog]):
    def __init__(
        self, session: Session | AsyncCassandraSession, *, timeout_seconds: float = 5
    ) -> None:
        super().__init__(
            session,
            model=SavedDialog,
            kind="SAVED",
            timeout_seconds=timeout_seconds,
            identity=lambda dialog: "saved:" + str(dialog.user_id),
        )

    async def get_by_owner(self, user_id: UUID) -> SavedDialog | None:
        return await self._get_by_key("saved:" + str(user_id))
