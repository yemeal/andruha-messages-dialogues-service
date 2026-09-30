import subprocess
import sys
from pathlib import Path


def test_use_cases_import_without_transport_infrastructure_or_dispatching() -> None:
    source = Path(__file__).resolve().parents[3] / "src"
    program = """
import importlib
import importlib.abc
import sys

sys.path.insert(0, sys.argv[1])

class ForbiddenDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        roots = (
            'app.infrastructure', 'app.entrypoints', 'app.core',
            'app.application.services', 'app.application.dispatching',
            'fastapi', 'starlette', 'cassandra', 'sqlalchemy',
        )
        if any(fullname == root or fullname.startswith(root + '.') for root in roots):
            raise ImportError('Forbidden application dependency: ' + fullname)
        return None

sys.meta_path.insert(0, ForbiddenDependencies())
for name in (
    'dialogues.create_direct', 'dialogues.create_saved',
    'groups.add_member', 'groups.remove_member',
    'groups.send_message', 'groups.advance_receipt',
):
    for module in ('command', 'handler'):
        importlib.import_module('app.application.commands.' + name + '.' + module)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(source)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
