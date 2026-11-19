import pytest
from cqltrack.config import Config

from app.infrastructure.persistence.cassandra import connection


@pytest.mark.asyncio
async def test_invalid_admission_limit_is_rejected_before_allocating_native_cluster(
    monkeypatch,
):
    def cluster_must_not_be_created(*args, **kwargs):
        raise AssertionError(
            "Invalid lifecycle configuration must not allocate native resources"
        )

    monkeypatch.setattr(connection, "Cluster", cluster_must_not_be_created)
    with pytest.raises(ValueError, match="in-flight limit"):
        async with connection.cassandra_connection(
            Config(keyspace="messages"), max_in_flight=0
        ):
            pytest.fail("Invalid connection configuration was accepted")
