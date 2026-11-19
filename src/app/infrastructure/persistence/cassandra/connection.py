"""Async connection scope; only native connect/shutdown use a lifecycle executor."""

import asyncio
import ssl
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from cassandra import ConsistencyLevel
from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile, Session
from cassandra.policies import DCAwareRoundRobinPolicy
from cassandra.query import named_tuple_factory
from cqltrack.config import Config
from pydantic import TypeAdapter

from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession
from app.infrastructure.persistence.cassandra.migration_schema import validate_keyspace

PATH_VALUE = TypeAdapter(str | None)
CONSISTENCIES = {
    "ANY": ConsistencyLevel.ANY,
    "ONE": ConsistencyLevel.ONE,
    "TWO": ConsistencyLevel.TWO,
    "THREE": ConsistencyLevel.THREE,
    "QUORUM": ConsistencyLevel.QUORUM,
    "ALL": ConsistencyLevel.ALL,
    "LOCAL_QUORUM": ConsistencyLevel.LOCAL_QUORUM,
    "EACH_QUORUM": ConsistencyLevel.EACH_QUORUM,
    "SERIAL": ConsistencyLevel.SERIAL,
    "LOCAL_SERIAL": ConsistencyLevel.LOCAL_SERIAL,
    "LOCAL_ONE": ConsistencyLevel.LOCAL_ONE,
}


def _open_native(config: Config) -> tuple[Cluster, Session]:
    if config.secure_connect_bundle:
        raise ValueError("This service uses native Cassandra, not an Astra bundle")
    if bool(config.username) != bool(config.password):
        raise ValueError("Cassandra username and password must be configured together")
    auth = (
        PlainTextAuthProvider(username=config.username, password=config.password)
        if config.username
        else None
    )
    context = None
    if config.ssl_enabled:
        context = ssl.create_default_context(
            cafile=PATH_VALUE.validate_python(config.ssl_ca_certs)
        )
        if not config.ssl_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        certificate = PATH_VALUE.validate_python(config.ssl_certfile)
        if certificate:
            context.load_cert_chain(
                certificate,
                PATH_VALUE.validate_python(config.ssl_keyfile),
            )
    try:
        consistency = CONSISTENCIES[config.consistency]
    except KeyError as error:
        raise ValueError("Unknown Cassandra consistency level") from error
    cluster = Cluster(
        contact_points=config.contact_points,
        port=config.port,
        auth_provider=auth,
        protocol_version=5,
        connect_timeout=config.connect_timeout,
        ssl_context=context,
        max_schema_agreement_wait=config.schema_agreement_wait,
        execution_profiles={
            EXEC_PROFILE_DEFAULT: ExecutionProfile(
                load_balancing_policy=DCAwareRoundRobinPolicy(),
                row_factory=named_tuple_factory,
                consistency_level=consistency,
                serial_consistency_level=ConsistencyLevel.SERIAL,
                request_timeout=config.request_timeout,
            )
        },
    )
    try:
        return cluster, cluster.connect()
    except BaseException:
        cluster.shutdown()
        raise


async def _settled[T](job: asyncio.Future[T]) -> tuple[T, bool]:
    interrupted = False
    while True:
        try:
            return await asyncio.shield(job), interrupted
        except asyncio.CancelledError:
            if job.cancelled():
                raise
            interrupted = True


@asynccontextmanager
async def cassandra_connection(
    config: Config, *, max_in_flight: int = 128
) -> AsyncIterator[AsyncCassandraSession]:
    if max_in_flight < 1:
        raise ValueError("Cassandra in-flight limit must be positive")
    keyspace = validate_keyspace(config.keyspace)
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cassandra-lifecycle")
    opening = loop.run_in_executor(pool, _open_native, config)
    try:
        try:
            cluster, native = await asyncio.shield(opening)
        except BaseException:
            # Cancellation does not stop the driver's synchronous connect. Wait
            # asynchronously and close any resource it produced before propagating.
            try:
                (cluster, _), _ = await _settled(opening)
            except BaseException:
                pass  # _open_native closes a failed connection itself.
            else:
                await _settled(loop.run_in_executor(pool, cluster.shutdown))
            raise
        session = AsyncCassandraSession(native, max_in_flight=max_in_flight)
        try:
            await session.execute("USE " + keyspace)
            yield session
        finally:
            interrupted = False
            try:
                _, interrupted = await _settled(asyncio.create_task(session.aclose()))
            finally:
                _, closing_interrupted = await _settled(
                    loop.run_in_executor(pool, cluster.shutdown)
                )
            if interrupted or closing_interrupted:
                raise asyncio.CancelledError()
    finally:
        # Native shutdown has completed; joining the idle executor must not block
        # the application loop. No query is ever submitted to this executor.
        pool.shutdown(wait=False)
