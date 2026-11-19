"""Check migration CLI in its runtime image against exclusively owned Cassandra."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def run(args, *, capture=False, check=True, timeout=60):
    return subprocess.run(
        args,
        check=check,
        text=True,
        timeout=timeout,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else None,
    )


def smoke(image, result_file):
    versions = [1, 2, 3, 4]
    image_id = run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], capture=True
    ).stdout.strip()
    suffix = uuid4().hex[:12]
    network, cassandra = f"messages-smoke-{suffix}", f"messages-cassandra-{suffix}"
    keyspace = "messages_smoke_" + uuid4().hex
    containers = set()
    checks = []
    network_created = False
    network_removed = False

    def cli(command, *options):
        name = f"messages-cli-{suffix}-{len(checks)}"
        containers.add(name)
        try:
            output = run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--network",
                    network,
                    "--env",
                    f"CQLTRACK_CONTACT_POINTS={cassandra}",
                    "--env",
                    "CQLTRACK_PORT=9042",
                    "--env",
                    f"CQLTRACK_KEYSPACE={keyspace}",
                    image_id,
                    "python",
                    "-m",
                    "app.entrypoints.migrations",
                    command,
                    *options,
                ],
                capture=True,
            )
            return json.loads(output.stdout)
        finally:
            run(["docker", "rm", "--force", name], check=False, capture=True)

    try:
        run(["docker", "network", "create", network])
        network_created = True
        containers.add(cassandra)
        run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                cassandra,
                "--network",
                network,
                "--env",
                "MAX_HEAP_SIZE=512M",
                "--env",
                "HEAP_NEWSIZE=128M",
                "cassandra:5.0.8-bookworm",
            ]
        )
        print(f"Disposable migration smoke: {cassandra}", flush=True)
        deadline = time.monotonic() + 180
        while run(
            [
                "docker",
                "exec",
                cassandra,
                "cqlsh",
                "-e",
                "SELECT release_version FROM system.local;",
            ],
            capture=True,
            check=False,
        ).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Disposable Cassandra startup timed out")
            time.sleep(1)
        run(
            [
                "docker",
                "exec",
                cassandra,
                "cqlsh",
                "-e",
                f"CREATE KEYSPACE {keyspace} WITH replication = "
                "{'class':'SimpleStrategy','replication_factor':1};",
            ]
        )
        initial = cli("status")
        assert [item["status"] for item in initial["migrations"]] == ["pending"] * len(
            versions
        )
        checks.append("read-only status before migration")
        assert cli("migrate")["changedVersions"] == versions
        checks.append("async upgrade")
        assert all(item["status"] == "applied" for item in cli("status")["migrations"])
        checks.append("applied status")
        assert [item["version"] for item in cli("history")] == versions
        checks.append("async history")
        assert cli("diff", "--target-keyspace", keyspace) == []
        checks.append("async schema inspection")
        assert cli("rollback", "--steps", "1")["changedVersions"] == [versions[-1]]
        checks.append("async downgrade")
        assert cli("migrate")["changedVersions"] == [versions[-1]]
        checks.append("remigrate")
        assert (
            cli("rollback", "--steps", str(len(versions)))["changedVersions"]
            == versions[::-1]
        )
        checks.append("full explicit downgrade")
    finally:
        for name in containers:
            run(["docker", "rm", "--force", name], check=False, capture=True)
        if network_created:
            network_removed = (
                run(
                    ["docker", "network", "rm", network], check=False, capture=True
                ).returncode
                == 0
            )
    if not network_removed:
        raise RuntimeError("Owned Docker network cleanup was not confirmed")
    if result_file:
        result_file.write_text(
            json.dumps(
                {
                    "image": image,
                    "image_id": image_id,
                    "passed": len(checks),
                    "checks": checks,
                    "cleanup_complete": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(
        f"Migration image smoke: {len(checks)} passed; owned resources removed",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--result-file", type=Path)
    args = parser.parse_args()
    smoke(args.image, args.result_file)
