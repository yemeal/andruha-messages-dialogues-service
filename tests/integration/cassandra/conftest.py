import asyncio
import os
from uuid import uuid7

import pytest
from cassandra import OperationTimedOut
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
from cassandra.policies import DCAwareRoundRobinPolicy
from cassandra.query import dict_factory

from app.infrastructure.persistence.cassandra.migrations import migrate


@pytest.fixture
def lost_commit_response():
    class LostResponse:
        def __init__(self, response):
            self.response = response

        def add_callbacks(self, callback, errback):
            return self.response.add_callbacks(
                lambda _rows: errback(OperationTimedOut()),
                errback,
            )

    return LostResponse


@pytest.fixture
def unmigrated_cassandra_session():
    host = os.environ["MESSAGES_TEST_CASSANDRA_HOST"]
    port = int(os.environ["MESSAGES_TEST_CASSANDRA_PORT"])
    keyspace = "messages_test_" + uuid7().hex
    cluster = Cluster(
        [host],
        port=port,
        protocol_version=5,
        execution_profiles={
            EXEC_PROFILE_DEFAULT: ExecutionProfile(
                load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="datacenter1"),
                row_factory=dict_factory,
            )
        },
    )
    session = cluster.connect()
    try:
        session.execute(
            f"CREATE KEYSPACE {keyspace} WITH replication = "
            "{'class': 'SimpleStrategy', 'replication_factor': 1}"
        )
        session.set_keyspace(keyspace)
        yield session
    finally:
        session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")
        cluster.shutdown()


@pytest.fixture
def cassandra_session(unmigrated_cassandra_session):
    asyncio.run(migrate(unmigrated_cassandra_session))
    return unmigrated_cassandra_session
