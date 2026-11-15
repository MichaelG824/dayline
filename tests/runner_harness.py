"""A real sandbox runner in this process, reached over HTTP like production:
for Docker-backed tests of code that talks to the runner through
:class:`~dayline.adapters.sandbox.RunnerSandboxClient`. Needs Docker and the
runner's dependencies (``uv sync --extra dev``)."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import uvicorn

from dayline.adapters.sandbox import RunnerSandboxClient
from dayline_runner.app import create_app
from dayline_runner.config import Settings
from dayline_runner.manager import SandboxManager
from dayline_runner.packs import load_packs

PACKS_DIR = Path(__file__).resolve().parents[1] / "sandbox" / "packs"
SECRET = "g" * 40


@contextlib.contextmanager
def running_runner(cleanup_prefixes: tuple[str, ...]) -> Iterator[RunnerSandboxClient]:
    """Build the packs, serve the runner on a free port, and on the way out
    destroy every sandbox whose id starts with one of ``cleanup_prefixes``."""
    settings = Settings(secret=SECRET, idle_timeout_s=900, hard_cap_s=1800, max_running=2)
    manager = SandboxManager(docker.from_env(), settings, load_packs(PACKS_DIR))
    manager.build_packs()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(manager=manager, settings=settings),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        yield RunnerSandboxClient(f"http://127.0.0.1:{port}", SECRET)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        labelled = manager._client.containers.list(all=True, filters={"label": "dayline.sandbox"})
        for container in labelled:
            sandbox_id = container.labels.get("dayline.sandbox.id", "")
            if sandbox_id.startswith(cleanup_prefixes):
                manager.destroy(sandbox_id)
