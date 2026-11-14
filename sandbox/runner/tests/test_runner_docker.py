"""Integration tests against a real Docker daemon, using the shipped packs.

Opt in with ``RUN_DOCKER_TESTS=1`` (and ``DOCKER_HOST`` if the socket is not
at the default path). The first run builds the pack images.
"""

from __future__ import annotations

import dataclasses
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

docker = pytest.importorskip("docker")

from dayline_runner.config import Settings  # noqa: E402
from dayline_runner.manager import (  # noqa: E402
    SandboxBusy,
    SandboxConflict,
    SandboxManager,
    SandboxNotFound,
)
from dayline_runner.packs import load_packs  # noqa: E402

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1 to run"
    ),
]

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"

CALC = {
    "calc.py": "def add(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n",
}


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def client() -> docker.DockerClient:
    return docker.from_env()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def manager(client: docker.DockerClient, clock: Clock) -> Iterator[SandboxManager]:
    packs = load_packs(PACKS_DIR)
    # A short test timeout keeps the runaway-test case quick.
    packs["python"] = dataclasses.replace(packs["python"], test_timeout_s=5)
    settings = Settings(secret="x" * 32, idle_timeout_s=60, hard_cap_s=600, retain_s=3600)
    m = SandboxManager(client, settings, packs, clock=clock)
    m.build_packs()
    made: list[str] = []
    original = m.create

    def create(sandbox_id: str, *args: object) -> dict[str, object]:
        made.append(sandbox_id)
        return original(sandbox_id, *args)  # type: ignore[arg-type]

    m.create = create  # type: ignore[method-assign]
    yield m
    for sandbox_id in made:
        m.destroy(sandbox_id)


def _id() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


def test_python_round_trip(manager: SandboxManager) -> None:
    sid = _id()
    manager.create(sid, "python", CALC)
    assert [e.path for e in manager.list_files(sid)] == ["calc.py", "tests/test_calc.py"]
    assert manager.run_tests(sid).status == "failed"

    opened = manager.read_file(sid, "calc.py")
    manager.write_file(sid, "calc.py", "def add(a, b):\n    return a + b\n", opened["version"])
    with pytest.raises(SandboxConflict):
        manager.write_file(sid, "calc.py", "stale", opened["version"])
    report = manager.run_tests(sid)
    assert (report.status, report.passed) == ("passed", 1)
    assert manager.snapshot(sid)["files"]["calc.py"].endswith("a + b\n")


def test_typescript_round_trip(manager: SandboxManager) -> None:
    sid = _id()
    files = {
        "src/sum.ts": "export const sum = (a: number, b: number) => a + b;\n",
        "src/sum.test.ts": (
            "import { expect, test } from 'vitest';\nimport { sum } from './sum';\n"
            "test('adds', () => expect(sum(1, 2)).toBe(3));\n"
        ),
    }
    manager.create(sid, "typescript", files)
    report = manager.run_tests(sid)
    assert (report.status, report.passed) == ("passed", 1), report.output


def test_lockdown(manager: SandboxManager) -> None:
    sid = _id()
    manager.create(sid, "python", {})
    container = manager._running(sid)

    def run(cmd: str) -> tuple[int, str]:
        code, out = manager._exec(container, ["sh", "-c", cmd])
        return code, out.decode()

    assert run("id -u")[1].strip() == "1000"
    assert run("touch /etc/owned")[0] != 0  # Read-only root filesystem.
    code, out = run(
        "python -c \"import urllib.request as u; u.urlopen('http://1.1.1.1', timeout=3)\""
    )
    assert code != 0 and "unreachable" in out.lower()
    # A process that blows the memory limit is killed, not the host.
    code, _ = run('python -c "b = bytearray(2 * 1024 ** 3)"')
    assert code != 0


def test_runaway_tests_time_out(manager: SandboxManager) -> None:
    sid = _id()
    manager.create(sid, "python", {"test_loop.py": "def test_forever():\n    while True: pass\n"})
    report = manager.run_tests(sid)
    assert report.status == "timeout"
    assert "stopped after 5 seconds" in report.output


def test_terminal(manager: SandboxManager) -> None:
    sid = _id()
    manager.create(sid, "python", {})
    handle = manager.open_pty(sid, 80, 24)
    try:
        handle.send(b"echo $((6 * 7))\n")
        out = b""
        deadline = time.time() + 10
        while b"42" not in out and time.time() < deadline:
            out += handle.recv()
        assert b"42" in out
    finally:
        manager.close_pty(handle)


def test_terminal_commands_are_logged_once_each(manager: SandboxManager) -> None:
    sid = _id()
    manager.create(sid, "python", {})
    for _ in range(2):  # A second shell (a reconnect) must not re-log the first's commands.
        handle = manager.open_pty(sid, 80, 24)
        try:
            for line in (b"true\n", b"\n", b"false\n", b"echo  'two  spaces'\n"):
                handle.send(line)
                time.sleep(0.3)
            deadline = time.time() + 10
            out = b""
            while out.count(b"$ ") < 5 and time.time() < deadline:
                out += handle.recv()
        finally:
            manager.close_pty(handle)
    runs = manager.commands(sid)
    assert [(r.command, r.exit_code) for r in runs] == [
        ("true", 0),
        ("false", 1),
        ("echo  'two  spaces'", 0),
    ] * 2
    assert all(r.at > 0 for r in runs)
    # The log is hidden from the file tree and the snapshot.
    assert manager.list_files(sid) == []
    assert manager.snapshot(sid)["files"] == {}


def test_idle_sandboxes_stop_resume_and_are_deleted_later(
    manager: SandboxManager, clock: Clock
) -> None:
    sid = _id()
    manager.create(sid, "python", CALC)
    clock.now += 61
    manager.reap()
    assert manager.info(sid)["state"] == "stopped"
    with pytest.raises(SandboxConflict):
        manager.list_files(sid)
    # Files are still readable while stopped, and it can be resumed.
    assert "calc.py" in manager.snapshot(sid)["files"]
    assert manager.resume(sid)["state"] == "running"

    clock.now += 601  # Past the hard cap: stopped and can't come back.
    manager.reap()
    with pytest.raises(SandboxConflict, match="time limit"):
        manager.resume(sid)
    clock.now += 3600
    manager.reap()
    with pytest.raises(SandboxNotFound):
        manager.info(sid)


def test_running_sandboxes_are_capped(manager: SandboxManager) -> None:
    manager.create(_id(), "python", {})
    manager.create(_id(), "python", {})
    with pytest.raises(SandboxBusy):
        manager.create(_id(), "python", {})
