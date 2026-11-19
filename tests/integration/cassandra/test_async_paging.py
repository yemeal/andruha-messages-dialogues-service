import asyncio

import pytest
from cassandra.query import SimpleStatement

from app.infrastructure.persistence.cassandra.async_session import AsyncCassandraSession


@pytest.mark.asyncio
async def test_pages_are_fetched_explicitly_through_async_api(
    cassandra_session, monkeypatch
):
    def synchronous_query_is_forbidden(*args, **kwargs):
        raise AssertionError("Paging must not use synchronous native queries")

    monkeypatch.setattr(cassandra_session, "execute", synchronous_query_is_forbidden)
    db = AsyncCassandraSession(cassandra_session, max_in_flight=3)
    await db.execute(
        "CREATE TABLE paging_probe (bucket int, position int, PRIMARY KEY ((bucket), position))"
    )
    await asyncio.gather(
        *(
            db.execute(
                "INSERT INTO paging_probe (bucket, position) VALUES (1, %s)",
                (position,),
            )
            for position in range(20)
        )
    )
    query = SimpleStatement(
        "SELECT position FROM paging_probe WHERE bucket=1", fetch_size=3
    )
    first = await db.execute(query)
    assert len(first.current_rows) == 3
    assert first.paging_state is not None
    with pytest.raises(TypeError):
        iter(first)
    rows = await db.fetch_all(query, max_rows=20, timeout=10)
    assert [row["position"] for row in rows] == list(range(20))
    with pytest.raises(ValueError, match="row limit exceeded"):
        await db.fetch_all(query, max_rows=19, timeout=10)
    await db.aclose()
