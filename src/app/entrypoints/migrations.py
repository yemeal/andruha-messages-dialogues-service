"""Versioned Cassandra migrations; every CQL operation uses the async adapter."""

import argparse
import asyncio
import json
from dataclasses import asdict

from cqltrack.config import Config

from app.infrastructure.persistence.cassandra.connection import cassandra_connection
from app.infrastructure.persistence.cassandra.migrations import MigrationRunner


async def run(arguments: argparse.Namespace) -> None:
    config = Config.load(arguments.config, profile=arguments.profile)
    async with cassandra_connection(config) as session:
        runner = MigrationRunner(
            session,
            config.migration_dir,
            agreement_seconds=config.schema_agreement_wait,
        )
        if arguments.command == "diff":
            print(
                json.dumps(
                    [
                        asdict(item)
                        for item in await runner.diff(arguments.target_keyspace)
                    ]
                )
            )
            return
        if arguments.command == "history":
            print(
                json.dumps(
                    [item.model_dump(mode="json") for item in await runner.history()]
                )
            )
            return
        changed = []
        if arguments.command == "migrate":
            changed = await runner.migrate(resume=arguments.resume)
        elif arguments.command == "rollback":
            changed = await runner.rollback(arguments.steps, resume=arguments.resume)
        print(
            json.dumps(
                {
                    "changedVersions": [item.version for item in changed],
                    "migrations": [asdict(item) for item in await runner.status()],
                }
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("migrate", "rollback", "status", "history", "diff")
    )
    parser.add_argument("--config", default="cqltrack.yml")
    parser.add_argument("--profile")
    parser.add_argument("--steps", type=int, default=1)
    parser.add_argument("--target-keyspace")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Rerun a partial migration after operator inspection",
    )
    arguments = parser.parse_args()
    if arguments.command == "diff" and not arguments.target_keyspace:
        parser.error("diff requires --target-keyspace")
    if arguments.resume and arguments.command not in {"migrate", "rollback"}:
        parser.error("--resume applies only to migrate/rollback")
    asyncio.run(run(arguments))


if __name__ == "__main__":
    main()
