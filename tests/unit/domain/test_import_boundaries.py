import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def test_domain_imports_without_application_or_external_adapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_path = Path(__file__).resolve().parents[3] / "src"
    monkeypatch.setenv("PYTHONPATH", str(source_path))
    script = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class RejectExternalDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                forbidden = (
                    "app.application", "app.infrastructure", "app.entrypoints",
                    "app.core", "fastapi", "starlette", "sqlalchemy",
                    "cassandra", "kafka", "aiokafka", "redis", "structlog",
                )
                if any(fullname == name or fullname.startswith(name + ".")
                       for name in forbidden):
                    raise ImportError(f"Domain imports forbidden module: {fullname}")

        sys.meta_path.insert(0, RejectExternalDependencies())

        from app.domain import DirectDialog, DirectParticipants
        from app.domain.exceptions import (
            DomainError, InvalidDomainTimestampError,
            NotDialogParticipantError, SelfDialogNotAllowedError,
        )
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
