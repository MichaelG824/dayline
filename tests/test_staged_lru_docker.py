"""The LRU staged problem in a real sandbox: its hidden tests behave the same
in the Python pack's locked-down container (one CPU, no network) as they do
locally - in particular, stage 4 still catches a cache with no lock.

Opt in with ``RUN_DOCKER_TESTS=1``, like the runner's own Docker tests.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

docker = pytest.importorskip("docker")

from dayline.mock import staged  # noqa: E402
from dayline.models import StageAttempt, StageStatus  # noqa: E402
from dayline_runner.config import Settings  # noqa: E402
from dayline_runner.manager import SandboxManager  # noqa: E402
from dayline_runner.packs import load_packs  # noqa: E402

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1 to run"
    ),
]

PACKS_DIR = Path(__file__).resolve().parents[1] / "sandbox" / "packs"
LRU = staged.builtin_staged_problems()["lru-cache"]


@pytest.fixture
def sandbox() -> Iterator[tuple[SandboxManager, str]]:
    manager = SandboxManager(docker.from_env(), Settings(secret="x" * 32), load_packs(PACKS_DIR))
    manager.build_packs()
    sandbox_id = f"test-{uuid.uuid4().hex[:10]}"
    manager.create(sandbox_id, LRU.pack, LRU.starter)
    yield manager, sandbox_id
    manager.destroy(sandbox_id)


def _run_stage_4(manager: SandboxManager, sandbox_id: str, code: str) -> bool:
    manager.write_file(sandbox_id, "lru_cache.py", code, None)
    attempts = [StageAttempt(status=StageStatus.PASSED) for _ in range(3)]
    attempts.append(StageAttempt(status=StageStatus.ACTIVE))
    report = manager.run_hidden_tests(sandbox_id, staged.hidden_files(LRU, attempts)).to_json()
    return staged.record_run(LRU, attempts, report)


def test_stage_4_passes_the_reference_and_catches_a_missing_lock(
    sandbox: tuple[SandboxManager, str],
) -> None:
    manager, sandbox_id = sandbox
    assert _run_stage_4(manager, sandbox_id, LRU.references[4]) is True
    for _ in range(3):
        assert _run_stage_4(manager, sandbox_id, LRU.references[3]) is False
