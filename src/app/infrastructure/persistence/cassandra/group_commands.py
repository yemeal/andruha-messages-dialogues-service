"""First real Cassandra slice: canonical group creation and membership CAS."""

from uuid import UUID

from cassandra.cluster import Session
from pydantic import BaseModel, Field, TypeAdapter

from app.application.dto.groups import GroupDialogDTO
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.exceptions.groups import (
    GroupCreationConflictError,
    GroupMembershipConflictError,
    GroupReadConflictError,
)
from app.application.ports.persistence.models import (
    GroupCreationAcceptance,
    GroupCreationIntent,
    GroupMembershipAcceptance,
    GroupMembershipIntent,
    GroupSnapshot,
)
from app.domain.aggregates.group_dialog import GroupDialog
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.statements import (
    DRIVER_ERRORS,
)
from app.infrastructure.persistence.cassandra.statements import (
    conditional_write as _write,
)
from app.infrastructure.persistence.cassandra.statements import (
    serial_read as _read,
)

CREATION_INTENT = TypeAdapter(GroupCreationIntent)
MEMBERSHIP_INTENT = TypeAdapter(GroupMembershipIntent)
MAX_WORKING_COMMANDS = 256


class _Head(BaseModel):
    command_kind: str | None = Field(default=None)
    revision: int = Field(ge=1)
    last_position: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    payload: str
    intent: str
    result: str


class _Acceptance(BaseModel):
    command_kind: str
    revision: int
    intent: str
    result: str


class CassandraGroupCommands:
    def __init__(
        self,
        session: Session | AsyncCassandraSession,
        *,
        timeout_seconds: float = 5,
        max_working_commands: int = MAX_WORKING_COMMANDS,
    ) -> None:
        if max_working_commands < 1:
            raise ValueError("Canonical working-command limit must be positive")
        self._session = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )
        self._timeout = timeout_seconds
        self._max_working_commands = max_working_commands

    async def _head(self, dialog_id: UUID) -> _Head | None:
        result = await self._session.execute(
            _read(
                "SELECT command_kind, revision, last_position, pending_count, payload, intent, result "
                "FROM canonical_rows WHERE dialog_id=%s AND row_key='state'"
            ),
            (dialog_id,),
            timeout=self._timeout,
        )
        row = result.one()
        return (
            _Head.model_validate(row, from_attributes=True) if row is not None else None
        )

    async def _acceptance(
        self, dialog_id: UUID, command_id: UUID
    ) -> _Acceptance | None:
        result = await self._session.execute(
            _read(
                "SELECT command_kind, revision, intent, result FROM canonical_rows "
                "WHERE dialog_id=%s AND row_key=%s"
            ),
            (dialog_id, "command:" + str(command_id)),
            timeout=self._timeout,
        )
        row = result.one()
        return (
            _Acceptance.model_validate(row, from_attributes=True)
            if row is not None
            else None
        )

    async def get_by_id(self, dialog_id: UUID) -> GroupSnapshot | None:
        try:
            head = await self._head(dialog_id)
        except DRIVER_ERRORS as error:
            raise StorageUnavailableError("Canonical group read unavailable") from error
        if head is None or head.command_kind not in (None, "GROUP"):
            return None
        return GroupSnapshot(
            dialog=GroupDialog.model_validate_json(head.payload),
            revision=head.revision,
            last_position=head.last_position,
        )

    async def get_creation_result(
        self, command_id: UUID
    ) -> GroupCreationAcceptance | None:
        try:
            head = await self._head(command_id)
        except DRIVER_ERRORS as error:
            raise StorageUnavailableError(
                "Group creation result unavailable"
            ) from error
        if head is None:
            return None
        if head.command_kind not in (None, "GROUP"):
            raise GroupCreationConflictError(
                "Creation operation belongs to another dialog kind"
            )
        return GroupCreationAcceptance(
            intent=CREATION_INTENT.validate_json(head.intent),
            result=GroupDialogDTO.model_validate_json(head.result),
        )

    async def create_or_get_group(
        self, group: GroupDialog, *, command_id: UUID, intent: GroupCreationIntent
    ) -> GroupCreationAcceptance:
        if group.id != command_id:
            raise ValueError("Group ID must equal the stable creation operation ID")
        candidate_result = GroupDialogDTO.from_domain(group)
        try:
            await self._session.execute(
                _write(
                    "INSERT INTO canonical_rows "
                    "(dialog_id, row_key, revision, last_position, pending_count, payload, intent, result, command_kind) "
                    "VALUES (%s, 'state', 1, 0, 0, %s, %s, %s, 'GROUP') IF NOT EXISTS"
                ),
                (
                    group.id,
                    group.model_dump_json(),
                    CREATION_INTENT.dump_json(intent).decode(),
                    candidate_result.model_dump_json(),
                ),
                timeout=self._timeout,
            )
        except DRIVER_ERRORS as error:
            accepted = await self.get_creation_result(command_id)
            if accepted is None:
                raise StorageUnavailableError(
                    "Group creation outcome is unknown"
                ) from error
            return accepted
        accepted = await self.get_creation_result(command_id)
        if accepted is None:
            raise StorageUnavailableError("Group creation was not confirmed")
        return accepted

    async def get_membership_result(
        self, dialog_id: UUID, command_id: UUID, *, at_revision: int
    ) -> GroupMembershipAcceptance | None:
        async def read_confirmed() -> _Acceptance | None:
            before = await self._head(dialog_id)
            if before is None or before.revision != at_revision:
                raise GroupReadConflictError("Group revision changed")
            record = await self._acceptance(dialog_id, command_id)
            after = await self._head(dialog_id)
            if after is None or after.revision != at_revision:
                raise GroupReadConflictError("Group revision changed")
            return record

        try:
            accepted = await read_confirmed()
        except DRIVER_ERRORS as error:
            raise StorageUnavailableError(
                "Membership result read unavailable"
            ) from error
        if accepted is None:
            return None
        if accepted.command_kind != "membership":
            raise GroupMembershipConflictError("Command kind conflicts")
        return GroupMembershipAcceptance(
            intent=MEMBERSHIP_INTENT.validate_json(accepted.intent),
            result=GroupDialogDTO.model_validate_json(accepted.result),
        )

    async def try_commit_membership(
        self,
        expected: GroupSnapshot,
        candidate: GroupDialog,
        *,
        command_id: UUID,
        intent: GroupMembershipIntent,
    ) -> bool:
        result_json = GroupDialogDTO.from_domain(candidate).model_dump_json()
        intent_json = MEMBERSHIP_INTENT.dump_json(intent).decode()

        async def commit() -> bool:
            head = await self._head(expected.dialog.id)
            if head is None or head.revision != expected.revision:
                return False
            if head.pending_count >= self._max_working_commands:
                raise StorageUnavailableError("Canonical recovery backlog is full")
            result = await self._session.execute(
                _write(
                    "BEGIN BATCH "
                    "UPDATE canonical_rows SET revision=%s, payload=%s, pending_count=%s "
                    "WHERE dialog_id=%s AND row_key='state' IF revision=%s; "
                    "INSERT INTO canonical_rows "
                    "(dialog_id, row_key, command_kind, revision, intent, result) "
                    "VALUES (%s, %s, 'membership', %s, %s, %s) IF NOT EXISTS; "
                    "APPLY BATCH"
                ),
                (
                    expected.revision + 1,
                    candidate.model_dump_json(),
                    head.pending_count + 1,
                    expected.dialog.id,
                    expected.revision,
                    expected.dialog.id,
                    "command:" + str(command_id),
                    expected.revision + 1,
                    intent_json,
                    result_json,
                ),
                timeout=self._timeout,
            )
            return result.was_applied

        try:
            return await commit()
        except DRIVER_ERRORS as error:
            try:
                accepted = await self._acceptance(expected.dialog.id, command_id)
            except DRIVER_ERRORS:
                raise StorageUnavailableError(
                    "Membership commit outcome is unknown"
                ) from error
            if accepted is None:
                raise StorageUnavailableError(
                    "Membership commit outcome is unknown"
                ) from error
            return accepted.intent == intent_json and accepted.result == result_json
