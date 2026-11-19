"""Business HTTP composition; persistence is always the real Cassandra adapter."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import UUID, uuid7

import httpx2
import structlog
from cassandra.cluster import Session
from cqltrack.config import Config
from pydantic import BaseModel

from app.application.commands.dialogues.create_direct.handler import (
    CreateDirectDialogHandler,
)
from app.application.commands.dialogues.create_saved.handler import (
    CreateSavedDialogHandler,
)
from app.application.commands.dialogues.send_direct_message.handler import (
    SendDirectMessageHandler,
)
from app.application.commands.dialogues.send_saved_message.handler import (
    SendSavedMessageHandler,
)
from app.application.exceptions.dependencies import StorageUnavailableError
from app.application.ports.identity.registered_users import RegisteredUsersProtocol
from app.application.queries.messages import MessageQueries
from app.core.jwt import JWTSettings
from app.core.messaging import MessagingSettings
from app.domain.clock import utc_now
from app.domain.value_objects.object_id import ObjectId
from app.infrastructure.identity.registered_users import HTTPRegisteredUsers
from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.connection import cassandra_connection
from app.infrastructure.persistence.cassandra.dialogues import (
    CassandraDirectDialogs,
    CassandraSavedDialogs,
)
from app.infrastructure.persistence.cassandra.messages import CassandraMessages
from app.infrastructure.security.access_tokens import AccessTokenVerifier
from app.infrastructure.security.cursors import CursorCodec

logger = structlog.get_logger()
REQUIRED_TABLES = frozenset(
    {
        "canonical_rows",
        "dialog_creations",
        "message_sends",
        "work_rows",
        "message_history",
        "message_lookup",
        "user_projection_state",
        "user_projection_results",
        "user_sync",
        "user_dialogs",
        "message_outbox",
    }
)


class AttachmentsUnavailableError(Exception):
    pass


class TextOnlyAttachments:
    async def require_ready(
        self, sender_id: UUID, attachments: tuple[ObjectId, ...]
    ) -> None:
        raise AttachmentsUnavailableError()


class _Table(BaseModel):
    table_name: str


class MessagingRuntime:
    def __init__(
        self,
        session: Session | AsyncCassandraSession,
        identity: RegisteredUsersProtocol,
        verifier: AccessTokenVerifier,
        cursors: CursorCodec,
    ) -> None:
        self.session = (
            session
            if isinstance(session, AsyncCassandraSession)
            else AsyncCassandraSession(session)
        )
        self.verifier = verifier
        self.cursors = cursors
        self.direct = CassandraDirectDialogs(self.session)
        self.saved = CassandraSavedDialogs(self.session)
        self.messages = CassandraMessages(self.session)
        self.views = self.messages.views
        self.create_direct = CreateDirectDialogHandler(
            self.direct, self.views, identity, utc_now, uuid7
        )
        self.create_saved = CreateSavedDialogHandler(
            self.saved, self.views, identity, utc_now, uuid7
        )
        attachments = TextOnlyAttachments()
        self.send_direct = SendDirectMessageHandler(
            self.direct, self.messages, attachments, utc_now, uuid7
        )
        self.send_saved = SendSavedMessageHandler(
            self.saved, self.messages, attachments, utc_now, uuid7
        )
        self.queries = MessageQueries(
            self.direct, self.saved, self.messages, self.views
        )

    async def validate_schema(self) -> None:
        page = await self.session.execute(
            "SELECT table_name FROM system_schema.tables WHERE keyspace_name=%s",
            (self.session.keyspace,),
        )
        tables = {
            _Table.model_validate(row, from_attributes=True).table_name
            for row in page.current_rows
        }
        if not tables >= REQUIRED_TABLES:
            raise StorageUnavailableError("Messages migrations are required")
        # Compilation also confirms the new send archive column exists.
        await self.session.execute(
            "SELECT acceptance FROM message_sends WHERE sender_id=%s AND client_message_id=%s",
            (uuid7(), uuid7()),
        )

    async def ready(self) -> bool:
        try:
            await self.validate_schema()
            return True
        except Exception:
            return False

    async def repair_loop(self, interval: float) -> None:
        while True:
            try:
                await self.messages.repair_pending(limit=32)
            except StorageUnavailableError:
                logger.warning("message recovery unavailable")
            await asyncio.sleep(interval)


@asynccontextmanager
async def messaging_runtime(
    settings: MessagingSettings,
) -> AsyncIterator[MessagingRuntime]:
    if settings.cursor_key_file is None:
        raise ValueError("MESSAGING_CURSOR_KEY_FILE is required for the business role")
    cursors = CursorCodec(settings.cursor_key_file.read_bytes())
    verifier = AccessTokenVerifier(JWTSettings())
    credential = settings.identity_service_token.get_secret_value()
    if not credential.strip():
        raise ValueError("MESSAGING_IDENTITY_SERVICE_TOKEN is required")
    config = Config.load(str(settings.cassandra_config))
    async with (
        cassandra_connection(config) as session,
        httpx2.AsyncClient(
            base_url=settings.identity_url, timeout=3, trust_env=False
        ) as client,
    ):
        runtime = MessagingRuntime(
            session,
            HTTPRegisteredUsers(client, service_token=credential),
            verifier,
            cursors,
        )
        await runtime.validate_schema()
        task = asyncio.create_task(
            runtime.repair_loop(settings.repair_interval_seconds)
        )
        try:
            yield runtime
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
