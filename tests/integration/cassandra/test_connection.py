import asyncio
import os
from threading import Event, get_ident

import pytest
from cassandra.cluster import Cluster, Session
from cqltrack.config import Config

from app.infrastructure.persistence.cassandra import connection
from app.infrastructure.persistence.cassandra.async_session import (
    CassandraSessionClosedError,
)


def configuration(keyspace):
    return Config(
        contact_points=[os.environ["MESSAGES_TEST_CASSANDRA_HOST"]],
        port=int(os.environ["MESSAGES_TEST_CASSANDRA_PORT"]),
        keyspace=keyspace,
        consistency="QUORUM",
        connect_timeout=5,
        request_timeout=5,
    )


@pytest.mark.asyncio
async def test_only_connect_and_shutdown_run_in_the_lifecycle_executor(
    unmigrated_cassandra_session,
    monkeypatch,
):
    threads = {}

    class ObservedCluster:
        def __init__(self, *args, **kwargs):
            self.native = Cluster(*args, **kwargs)

        def connect(self):
            threads["connect"] = get_ident()
            return self.native.connect()

        def shutdown(self):
            threads["shutdown"] = get_ident()
            return self.native.shutdown()

    def synchronous_query_is_forbidden(*args, **kwargs):
        raise AssertionError("Connection setup must use async USE/CQL")

    monkeypatch.setattr(connection, "Cluster", ObservedCluster)
    monkeypatch.setattr(Session, "execute", synchronous_query_is_forbidden)
    main_thread = get_ident()
    keyspace = unmigrated_cassandra_session.keyspace
    async with connection.cassandra_connection(configuration(keyspace)) as db:
        assert db.keyspace == keyspace
        result = await db.execute(
            "SELECT keyspace_name FROM system_schema.keyspaces WHERE keyspace_name=%s",
            (keyspace,),
        )
        assert result.one().keyspace_name == keyspace
        assert threads["connect"] != main_thread
    assert threads["shutdown"] == threads["connect"]
    with pytest.raises(CassandraSessionClosedError):
        await db.execute("SELECT release_version FROM system.local")


@pytest.mark.asyncio
async def test_cancelled_connection_opening_closes_the_late_native_resource(
    unmigrated_cassandra_session,
    monkeypatch,
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    proceed = Event()
    closed = []

    class SlowCluster:
        def __init__(self, *args, **kwargs):
            self.native = Cluster(*args, **kwargs)

        def connect(self):
            loop.call_soon_threadsafe(entered.set)
            if not proceed.wait(timeout=10):
                raise TimeoutError("Test did not release native connect")
            return self.native.connect()

        def shutdown(self):
            closed.append(get_ident())
            return self.native.shutdown()

    monkeypatch.setattr(connection, "Cluster", SlowCluster)
    context = connection.cassandra_connection(
        configuration(unmigrated_cassandra_session.keyspace)
    )
    opening = asyncio.create_task(context.__aenter__())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        opening.cancel()
        barrier = asyncio.Event()
        loop.call_soon(barrier.set)
        await barrier.wait()
        assert closed == []
    finally:
        proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await opening
    assert len(closed) == 1
    assert closed[0] != get_ident()
