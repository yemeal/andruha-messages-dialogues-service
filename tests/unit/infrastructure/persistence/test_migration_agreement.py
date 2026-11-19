from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid7

import pytest

from app.infrastructure.persistence.cassandra.migrations import (
    MigrationSession,
    SchemaAgreementError,
)


@dataclass(frozen=True)
class Host:
    name: str
    is_up: bool = True


class SchemaSession:
    def __init__(self, versions):
        self.versions = {
            Host(str(index)): version for index, version in enumerate(versions)
        }
        self.live_hosts = tuple(self.versions)
        self.statements = []

    def execution_profile_clone_update(self, *args, **kwargs):
        return "migration-profile"

    async def execute(self, query, parameters=None, *, host=None, **kwargs):
        self.statements.append(getattr(query, "query_string", query))
        if host is not None:
            return SimpleNamespace(
                one=lambda: SimpleNamespace(schema_version=self.versions[host])
            )
        return SimpleNamespace()


@pytest.mark.parametrize(
    "divergent", [False, True, None], ids=["agree", "differ", "unknown"]
)
@pytest.mark.asyncio
async def test_next_ddl_is_refused_until_all_known_live_nodes_agree(divergent):
    first = uuid7()
    versions = [first, first if divergent is False else uuid7() if divergent else None]
    session = SchemaSession(versions)
    elapsed = 0.0

    def monotonic():
        return elapsed

    async def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    boundary = MigrationSession(
        session, agreement_seconds=1, clock=monotonic, pause=sleep
    )

    async def run_migration():
        await boundary.execute("CREATE TABLE first_table (id uuid PRIMARY KEY)")
        await boundary.execute("ALTER TABLE first_table ADD second_field text")

    if divergent is False:
        await run_migration()
        assert any(query.startswith("ALTER TABLE") for query in session.statements)
    else:
        with pytest.raises(SchemaAgreementError):
            await run_migration()
        assert not any(query.startswith("ALTER TABLE") for query in session.statements)
