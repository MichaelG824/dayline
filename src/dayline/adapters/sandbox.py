"""Sandbox client interface + in-memory fake + the real sandbox-runner client.

Live mock sessions run code in a sandbox owned by the separate runner service
(``sandbox/runner``), the only process with Docker access. Dayline never
touches Docker: it calls the runner over HTTP (files, tests) and WebSocket
(the terminal) with a shared secret. A sandbox's id is its session's id.

Runner JSON is passed through as plain dicts in camelCase (the runner's wire
format); the shapes are documented on each method.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import os
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

import httpx
import websockets

# Test runs can take the pack's full timeout (60s by default) plus startup.
_TEST_TIMEOUT_S = 120.0
_DEFAULT_TIMEOUT_S = 30.0


class SandboxUnavailable(Exception):
    """The runner is not configured or cannot be reached."""


class SandboxRequestError(Exception):
    """The runner refused a request; ``status_code`` is its HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TerminalConnection(Protocol):
    """A live shell: send keystrokes (bytes) or control JSON (str); iterate
    to receive output until the shell exits."""

    async def send(self, message: bytes | str) -> None: ...

    def __aiter__(self) -> AsyncIterator[bytes | str]: ...


@runtime_checkable
class SandboxClient(Protocol):
    def packs(self) -> list[dict[str, Any]]:
        """``[{name, displayName, editorLanguage, state, error}]``."""
        ...

    def create(self, sandbox_id: str, pack: str, files: dict[str, str]) -> dict[str, Any]:
        """Start a sandbox. Returns its info (see :meth:`info`)."""
        ...

    def info(self, sandbox_id: str) -> dict[str, Any]:
        """``{id, pack, state: running|stopped, createdAt, expiresAt, idleTimeoutS}``
        (times in epoch seconds)."""
        ...

    def resume(self, sandbox_id: str) -> dict[str, Any]: ...

    def destroy(self, sandbox_id: str) -> None: ...

    def list_files(self, sandbox_id: str) -> list[dict[str, Any]]:
        """``[{path, size, version}]``, sorted by path."""
        ...

    def read_file(self, sandbox_id: str, path: str) -> dict[str, Any]:
        """``{path, content, version}``."""
        ...

    def write_file(
        self, sandbox_id: str, path: str, content: str, base_version: str | None
    ) -> dict[str, Any]:
        """``{path, version}``. A stale ``base_version`` is a 409."""
        ...

    def run_tests(self, sandbox_id: str) -> dict[str, Any]:
        """``{status, passed, failed, errors, skipped, duration_s, exit_code,
        output, cases: [{name, classname, outcome, message, duration_s}]}``."""
        ...

    def snapshot(self, sandbox_id: str) -> dict[str, Any]:
        """``{files: {path: content}, skipped: [path]}``; works once stopped."""
        ...

    def commands(self, sandbox_id: str) -> list[dict[str, Any]]:
        """Commands typed in the terminal, oldest first:
        ``[{at (epoch seconds), exitCode, command}]``; works once stopped."""
        ...

    def open_terminal(
        self, sandbox_id: str, cols: int, rows: int
    ) -> contextlib.AbstractAsyncContextManager[TerminalConnection]: ...


def runner_from_env() -> RunnerSandboxClient | None:
    """The real client when ``SANDBOX_RUNNER_URL`` is set, else ``None``
    (live sessions are then unavailable; everything else works)."""
    url = os.environ.get("SANDBOX_RUNNER_URL", "").strip().rstrip("/")
    if not url:
        return None
    secret = os.environ.get("SANDBOX_RUNNER_SECRET", "").strip()
    if not secret:
        raise RuntimeError("SANDBOX_RUNNER_URL is set but SANDBOX_RUNNER_SECRET is not.")
    return RunnerSandboxClient(url, secret)


class RunnerSandboxClient:
    """Talks to the sandbox runner service."""

    def __init__(self, base_url: str, secret: str) -> None:
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {secret}"}
        self._http = httpx.Client(
            base_url=base_url, headers=self._headers, timeout=_DEFAULT_TIMEOUT_S
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SandboxUnavailable(f"The sandbox runner is not reachable ({exc})") from exc
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail") or response.text)
            except ValueError:
                detail = response.text or response.reason_phrase
            raise SandboxRequestError(response.status_code, detail)
        return response.json() if response.content else None

    @staticmethod
    def _file_path(sandbox_id: str, path: str) -> str:
        return f"/sandboxes/{sandbox_id}/files/{quote(path)}"

    def packs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", "/packs")
        return result

    def create(self, sandbox_id: str, pack: str, files: dict[str, str]) -> dict[str, Any]:
        body = {"id": sandbox_id, "pack": pack, "files": files}
        result: dict[str, Any] = self._request("POST", "/sandboxes", json=body)
        return result

    def info(self, sandbox_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/sandboxes/{sandbox_id}")
        return result

    def resume(self, sandbox_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", f"/sandboxes/{sandbox_id}/resume")
        return result

    def destroy(self, sandbox_id: str) -> None:
        self._request("DELETE", f"/sandboxes/{sandbox_id}")

    def list_files(self, sandbox_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", f"/sandboxes/{sandbox_id}/files")
        return result

    def read_file(self, sandbox_id: str, path: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", self._file_path(sandbox_id, path))
        return result

    def write_file(
        self, sandbox_id: str, path: str, content: str, base_version: str | None
    ) -> dict[str, Any]:
        body = {"content": content, "baseVersion": base_version}
        result: dict[str, Any] = self._request(
            "PUT", self._file_path(sandbox_id, path), json=body
        )
        return result

    def run_tests(self, sandbox_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST", f"/sandboxes/{sandbox_id}/tests", timeout=_TEST_TIMEOUT_S
        )
        return result

    def snapshot(self, sandbox_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/sandboxes/{sandbox_id}/snapshot")
        return result

    def commands(self, sandbox_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", f"/sandboxes/{sandbox_id}/commands")
        return result

    @contextlib.asynccontextmanager
    async def open_terminal(
        self, sandbox_id: str, cols: int, rows: int
    ) -> AsyncIterator[TerminalConnection]:
        ws_base = "ws" + self._base_url.removeprefix("http")
        url = f"{ws_base}/sandboxes/{sandbox_id}/pty?cols={cols}&rows={rows}"
        try:
            connection = await websockets.connect(
                url, additional_headers=self._headers, max_size=2**20
            )
        except (OSError, websockets.WebSocketException) as exc:
            raise SandboxUnavailable(f"The sandbox runner is not reachable ({exc})") from exc
        try:
            yield connection
        finally:
            await connection.close()


# --------------------------------------------------------------------------- #
# In-memory fake
# --------------------------------------------------------------------------- #


def _version(content: str) -> str:
    return hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()


class _EchoTerminal:
    """Echoes input back, like a shell with nothing running."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | str | None] = asyncio.Queue()
        self.received: list[bytes | str] = []

    async def send(self, message: bytes | str) -> None:
        self.received.append(message)
        if message == b"exit\n":
            await self._queue.put(None)
        elif isinstance(message, bytes):
            await self._queue.put(message)

    def __aiter__(self) -> AsyncIterator[bytes | str]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes | str]:
        while (item := await self._queue.get()) is not None:
            yield item


class InMemorySandboxClient:
    """A working fake :class:`SandboxClient` for tests: files live in a dict,
    test runs return ``next_report`` (set it to script a run), and the
    terminal echoes."""

    PACKS = [
        {"name": "python", "displayName": "Python 3.12", "editorLanguage": "python"},
        {"name": "typescript", "displayName": "TypeScript", "editorLanguage": "typescript"},
    ]

    def __init__(self) -> None:
        self.sandboxes: dict[str, dict[str, Any]] = {}
        self.next_report: dict[str, Any] = {"status": "passed", "passed": 1, "cases": []}
        self.terminals: list[_EchoTerminal] = []
        self.unavailable = False

    def _check(self) -> None:
        if self.unavailable:
            raise SandboxUnavailable("The sandbox runner is not reachable (fake)")

    def _get(self, sandbox_id: str, running: bool = True) -> dict[str, Any]:
        self._check()
        box = self.sandboxes.get(sandbox_id)
        if box is None:
            raise SandboxRequestError(404, f"No sandbox {sandbox_id!r}")
        if running and box["state"] != "running":
            raise SandboxRequestError(409, "The sandbox is stopped")
        return box

    def packs(self) -> list[dict[str, Any]]:
        self._check()
        return [{**p, "state": "ready", "error": None} for p in self.PACKS]

    def create(self, sandbox_id: str, pack: str, files: dict[str, str]) -> dict[str, Any]:
        self._check()
        if sandbox_id in self.sandboxes:
            raise SandboxRequestError(409, "Sandbox already exists")
        self.sandboxes[sandbox_id] = {
            "id": sandbox_id,
            "pack": pack,
            "state": "running",
            "files": dict(files),
            "commands": [],
        }
        return self.info(sandbox_id)

    def info(self, sandbox_id: str) -> dict[str, Any]:
        box = self._get(sandbox_id, running=False)
        return {
            "id": sandbox_id,
            "pack": box["pack"],
            "state": box["state"],
            "createdAt": 1_800_000_000.0,
            "expiresAt": 1_800_005_400.0,
            "idleTimeoutS": 900,
        }

    def resume(self, sandbox_id: str) -> dict[str, Any]:
        self._get(sandbox_id, running=False)["state"] = "running"
        return self.info(sandbox_id)

    def stop(self, sandbox_id: str) -> None:
        """Test helper: what the runner's reaper does to an idle sandbox."""
        self._get(sandbox_id, running=False)["state"] = "stopped"

    def destroy(self, sandbox_id: str) -> None:
        self._check()
        self.sandboxes.pop(sandbox_id, None)

    def list_files(self, sandbox_id: str) -> list[dict[str, Any]]:
        files = self._get(sandbox_id)["files"]
        return [
            {"path": p, "size": len(c.encode()), "version": _version(c)}
            for p, c in sorted(files.items())
        ]

    def read_file(self, sandbox_id: str, path: str) -> dict[str, Any]:
        files = self._get(sandbox_id)["files"]
        if path not in files:
            raise SandboxRequestError(404, f"No file {path!r}")
        return {"path": path, "content": files[path], "version": _version(files[path])}

    def write_file(
        self, sandbox_id: str, path: str, content: str, base_version: str | None
    ) -> dict[str, Any]:
        files = self._get(sandbox_id)["files"]
        current = _version(files[path]) if path in files else ""
        if base_version is not None and base_version != current:
            raise SandboxRequestError(409, f"{path} changed since it was opened")
        files[path] = content
        return {"path": path, "version": _version(content)}

    def run_tests(self, sandbox_id: str) -> dict[str, Any]:
        self._get(sandbox_id)
        return copy.deepcopy(self.next_report)

    def snapshot(self, sandbox_id: str) -> dict[str, Any]:
        return {"files": dict(self._get(sandbox_id, running=False)["files"]), "skipped": []}

    def commands(self, sandbox_id: str) -> list[dict[str, Any]]:
        """Append to ``sandboxes[id]["commands"]`` to script terminal use."""
        return list(self._get(sandbox_id, running=False)["commands"])

    @contextlib.asynccontextmanager
    async def open_terminal(
        self, sandbox_id: str, cols: int, rows: int
    ) -> AsyncIterator[TerminalConnection]:
        self._get(sandbox_id)
        terminal = _EchoTerminal()
        self.terminals.append(terminal)
        yield terminal
