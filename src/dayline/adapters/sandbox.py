"""Sandbox client interface + in-memory fake + the real sandbox-runner client.

Live mock sessions run code in a sandbox owned by the separate runner service
(``sandbox/runner``), the only process with Docker access. Dayline never
touches Docker: it calls the runner over HTTP (files, tests) and WebSocket
(the terminal) with a shared secret. A sandbox's id is its session's id.

Runner JSON is passed through as plain dicts in camelCase (the runner's wire
format); the shapes are documented on each method.

A pack can run dev servers in the sandbox; :meth:`SandboxClient.preview`
and :meth:`SandboxClient.open_preview_socket` reach them through the
runner's preview proxy, so the browser never talks to the runner itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

import httpx
import websockets

# Test runs can take the pack's full timeout (up to 120s) plus startup.
_TEST_TIMEOUT_S = 180.0
_DEFAULT_TIMEOUT_S = 30.0
# A dev server's first page load compiles it; the runner allows 300s.
_PREVIEW_TIMEOUT = httpx.Timeout(30.0, read=310.0)
# The runner checks this against the sandbox's preview base (see preview.py there).
PREVIEW_BASE_HEADER = "X-Dayline-Preview-Base"


class SandboxUnavailable(Exception):
    """The runner is not configured or cannot be reached."""


class SandboxRequestError(Exception):
    """The runner refused a request; ``status_code`` is its HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(slots=True)
class PreviewResponse:
    """A dev server's answer through the runner, streamed. ``headers`` keeps
    repeats (``Set-Cookie``); ``aclose`` must run once the body is done."""

    status: int
    headers: list[tuple[str, str]]
    body: AsyncIterator[bytes]
    aclose: Callable[[], Awaitable[None]]


class PreviewSocket(Protocol):
    """A dev server's WebSocket: ``subprotocol`` is what it accepted."""

    @property
    def subprotocol(self) -> str | None: ...

    async def send(self, message: bytes | str) -> None: ...

    def __aiter__(self) -> AsyncIterator[bytes | str]: ...


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

    def create(
        self, sandbox_id: str, pack: str, files: dict[str, str], preview_base: str | None = None
    ) -> dict[str, Any]:
        """Start a sandbox (and its pack's dev servers). ``preview_base`` is
        the path the browser previews them under. Returns its info."""
        ...

    def info(self, sandbox_id: str) -> dict[str, Any]:
        """``{id, pack, state: running|stopped, createdAt, expiresAt, idleTimeoutS,
        previewBase}`` (times in epoch seconds)."""
        ...

    def check_dependencies(self, pack: str, files: dict[str, str]) -> list[str]:
        """Why ``files`` use dependencies the pack does not install (empty =
        fine). The pack's allowed list is ``packs()[i]["dependencies"]``."""
        ...

    def servers(self, sandbox_id: str) -> list[dict[str, Any]]:
        """The pack's dev servers: ``[{name, port, readyPath, state:
        stopped|starting|ready|exited, exitCode, startedAt, readyAt}]``."""
        ...

    def server_action(self, sandbox_id: str, name: str, action: str) -> list[dict[str, Any]]:
        """``start``, ``stop`` or ``restart`` a dev server; returns :meth:`servers`."""
        ...

    def server_logs(self, sandbox_id: str, name: str, since: int) -> dict[str, Any]:
        """``{lines, next, truncated}``: output lines numbered ``since`` on."""
        ...

    async def preview(
        self,
        sandbox_id: str,
        base: str,
        port: int,
        path: str,
        *,
        method: str,
        query: str,
        headers: list[tuple[str, str]],
        body: AsyncIterator[bytes] | None,
    ) -> PreviewResponse:
        """Forward a request to the dev server on ``port``. ``path`` is the
        raw, still-encoded part of the URL after the port (``""`` or
        ``"/..."``); ``base`` must be the sandbox's preview base. Runner
        refusals come back as responses marked ``X-Dayline-Preview-Error``."""
        ...

    def open_preview_socket(
        self,
        sandbox_id: str,
        base: str,
        port: int,
        path: str,
        *,
        query: str,
        headers: list[tuple[str, str]],
        subprotocols: list[str],
    ) -> contextlib.AbstractAsyncContextManager[PreviewSocket]: ...

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

    def run_hidden_tests(self, sandbox_id: str, files: dict[str, str]) -> dict[str, Any]:
        """Run test files the candidate never sees (``{path: content}``)
        against the workspace; same report shape as :meth:`run_tests`. The
        files exist in the sandbox for this run only."""
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
        self._async: httpx.AsyncClient | None = None

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

    def create(
        self, sandbox_id: str, pack: str, files: dict[str, str], preview_base: str | None = None
    ) -> dict[str, Any]:
        body = {"id": sandbox_id, "pack": pack, "files": files, "previewBase": preview_base}
        result: dict[str, Any] = self._request("POST", "/sandboxes", json=body)
        return result

    def check_dependencies(self, pack: str, files: dict[str, str]) -> list[str]:
        result: dict[str, Any] = self._request(
            "POST", f"/packs/{quote(pack)}/check", json={"files": files}
        )
        return list(result["problems"])

    def servers(self, sandbox_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request("GET", f"/sandboxes/{sandbox_id}/servers")
        return result

    def server_action(self, sandbox_id: str, name: str, action: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._request(
            "POST", f"/sandboxes/{sandbox_id}/servers/{quote(name)}/{quote(action)}"
        )
        return result

    def server_logs(self, sandbox_id: str, name: str, since: int) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "GET", f"/sandboxes/{sandbox_id}/servers/{quote(name)}/logs", params={"since": since}
        )
        return result

    def _preview_url(self, sandbox_id: str, port: int, path: str, query: str) -> str:
        return f"/sandboxes/{sandbox_id}/preview/{port}{path}" + (f"?{query}" if query else "")

    async def preview(
        self,
        sandbox_id: str,
        base: str,
        port: int,
        path: str,
        *,
        method: str,
        query: str,
        headers: list[tuple[str, str]],
        body: AsyncIterator[bytes] | None,
    ) -> PreviewResponse:
        if self._async is None:
            self._async = httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=_PREVIEW_TIMEOUT
            )
        request = self._async.build_request(
            method,
            self._preview_url(sandbox_id, port, path, query),
            headers=[*headers, (PREVIEW_BASE_HEADER, base)],
            content=body,
        )
        try:
            response = await self._async.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise SandboxUnavailable(f"The sandbox runner is not reachable ({exc})") from exc
        return PreviewResponse(
            status=response.status_code,
            headers=response.headers.multi_items(),
            body=response.aiter_raw(),
            aclose=response.aclose,
        )

    @contextlib.asynccontextmanager
    async def open_preview_socket(
        self,
        sandbox_id: str,
        base: str,
        port: int,
        path: str,
        *,
        query: str,
        headers: list[tuple[str, str]],
        subprotocols: list[str],
    ) -> AsyncIterator[PreviewSocket]:
        ws_base = "ws" + self._base_url.removeprefix("http")
        url = ws_base + self._preview_url(sandbox_id, port, path, query)
        try:
            connection = await websockets.connect(
                url,
                additional_headers=[
                    *headers,
                    *self._headers.items(),
                    (PREVIEW_BASE_HEADER, base),
                ],
                subprotocols=[websockets.Subprotocol(p) for p in subprotocols] or None,
                max_size=16 * 2**20,
                # The browser's own pings keep the socket open.
                ping_interval=None,
            )
        except websockets.InvalidStatus as exc:
            raise SandboxRequestError(exc.response.status_code, "Preview socket refused") from exc
        except (OSError, websockets.WebSocketException) as exc:
            raise SandboxUnavailable(f"The sandbox runner is not reachable ({exc})") from exc
        try:
            yield connection
        finally:
            await connection.close()

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

    def run_hidden_tests(self, sandbox_id: str, files: dict[str, str]) -> dict[str, Any]:
        try:
            result: dict[str, Any] = self._request(
                "POST",
                f"/sandboxes/{sandbox_id}/hidden-tests",
                json={"files": files},
                timeout=_TEST_TIMEOUT_S,
            )
        except SandboxRequestError as exc:
            # FastAPI's bare 404 for a route the runner does not have yet (a
            # missing sandbox says "No sandbox ...").
            if exc.status_code == 404 and exc.detail == "Not Found":
                raise SandboxRequestError(
                    501, "The sandbox runner is out of date: redeploy it to run staged rounds"
                ) from exc
            raise
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


class _EchoSocket(_EchoTerminal):
    def __init__(self, subprotocol: str | None) -> None:
        super().__init__()
        self.subprotocol = subprotocol

    async def send(self, message: bytes | str) -> None:
        self.received.append(message)
        await self._queue.put(None if message == "close" else message)


class InMemorySandboxClient:
    """A working fake :class:`SandboxClient` for tests: files live in a dict,
    test runs return ``next_report`` (set it to script a run), hidden test
    runs return ``hidden_report(files)`` (replace it to script them; each
    run's files are kept in ``hidden_runs``), and the terminal echoes.

    Packs with dev servers (``SERVERS``) report them ready once started;
    previews answer with ``preview_reply(request)`` (each request is kept in
    ``preview_requests``) and preview sockets echo until sent ``"close"``."""

    PACKS = [
        {"name": "python", "displayName": "Python 3.12", "editorLanguage": "python"},
        {"name": "typescript", "displayName": "TypeScript", "editorLanguage": "typescript"},
        {"name": "next-nest", "displayName": "Next.js + NestJS", "editorLanguage": "typescript"},
        {"name": "rails", "displayName": "Ruby 3.3 + Rails 8.1", "editorLanguage": "ruby"},
    ]
    SERVERS = {
        "next-nest": [
            {"name": "api", "port": 4000, "readyPath": None},
            {"name": "web", "port": 3000, "readyPath": ""},
        ],
        "rails": [{"name": "web", "port": 3000, "readyPath": None}],
    }

    def __init__(self) -> None:
        self.sandboxes: dict[str, dict[str, Any]] = {}
        self.next_report: dict[str, Any] = {"status": "passed", "passed": 1, "cases": []}
        self.hidden_runs: list[dict[str, str]] = []
        self.hidden_report: Callable[[dict[str, str]], dict[str, Any]] = lambda _files: {
            "status": "passed",
            "passed": 1,
            "cases": [],
        }
        self.terminals: list[_EchoTerminal] = []
        self.unavailable = False
        self.preview_requests: list[dict[str, Any]] = []
        self.preview_reply: Callable[[dict[str, Any]], tuple[int, list[tuple[str, str]], bytes]] = (
            lambda _request: (200, [("content-type", "text/html")], b"<h1>Notes</h1>")
        )
        self.preview_sockets: list[_EchoSocket] = []

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
        return [
            {**p, "state": "ready", "error": None, "servers": self.SERVERS.get(p["name"], [])}
            for p in self.PACKS
        ]

    def create(
        self, sandbox_id: str, pack: str, files: dict[str, str], preview_base: str | None = None
    ) -> dict[str, Any]:
        self._check()
        if sandbox_id in self.sandboxes:
            raise SandboxRequestError(409, "Sandbox already exists")
        self.sandboxes[sandbox_id] = {
            "id": sandbox_id,
            "pack": pack,
            "state": "running",
            "files": dict(files),
            "commands": [],
            "previewBase": preview_base,
            "servers": {s["name"]: "ready" for s in self.SERVERS.get(pack, [])},
            "logs": {s["name"]: [f"{s['name']} is ready"] for s in self.SERVERS.get(pack, [])},
        }
        return self.info(sandbox_id)

    def check_dependencies(self, pack: str, files: dict[str, str]) -> list[str]:
        self._check()
        return []

    def servers(self, sandbox_id: str) -> list[dict[str, Any]]:
        box = self._get(sandbox_id, running=False)
        running = box["state"] == "running"
        return [
            {
                **spec,
                "state": box["servers"][spec["name"]] if running else "stopped",
                "exitCode": None,
                "startedAt": None,
                "readyAt": None,
            }
            for spec in self.SERVERS.get(box["pack"], [])
        ]

    def server_action(self, sandbox_id: str, name: str, action: str) -> list[dict[str, Any]]:
        box = self._get(sandbox_id)
        if name not in box["servers"]:
            raise SandboxRequestError(404, f"No server {name!r}")
        if action not in ("start", "stop", "restart"):
            raise SandboxRequestError(400, f"Unknown server action {action!r}")
        box["servers"][name] = "stopped" if action == "stop" else "ready"
        box["logs"][name].append(f"[dayline] {action}")
        return self.servers(sandbox_id)

    def server_logs(self, sandbox_id: str, name: str, since: int) -> dict[str, Any]:
        lines = self._get(sandbox_id, running=False)["logs"].get(name)
        if lines is None:
            raise SandboxRequestError(404, f"No server {name!r}")
        return {"lines": lines[since:], "next": len(lines), "truncated": False}

    def _preview_box(self, sandbox_id: str, base: str, port: int) -> None:
        box = self._get(sandbox_id)
        ports = [s["port"] for s in self.SERVERS.get(box["pack"], [])]
        if not box["previewBase"] or base != box["previewBase"] or port not in ports:
            raise SandboxRequestError(404, "No such preview")

    async def preview(
        self,
        sandbox_id: str,
        base: str,
        port: int,
        path: str,
        *,
        method: str,
        query: str,
        headers: list[tuple[str, str]],
        body: AsyncIterator[bytes] | None,
    ) -> PreviewResponse:
        self._preview_box(sandbox_id, base, port)
        content = b"".join([chunk async for chunk in body]) if body is not None else b""
        request = {
            "port": port,
            "path": path,
            "method": method,
            "query": query,
            "headers": headers,
            "body": content,
        }
        self.preview_requests.append(request)
        status, reply_headers, reply = self.preview_reply(request)

        async def stream() -> AsyncIterator[bytes]:
            yield reply

        async def aclose() -> None:
            return None

        return PreviewResponse(status=status, headers=reply_headers, body=stream(), aclose=aclose)

    @contextlib.asynccontextmanager
    async def open_preview_socket(
        self,
        sandbox_id: str,
        base: str,
        port: int,
        path: str,
        *,
        query: str,
        headers: list[tuple[str, str]],
        subprotocols: list[str],
    ) -> AsyncIterator[PreviewSocket]:
        self._preview_box(sandbox_id, base, port)
        socket = _EchoSocket(subprotocols[0] if subprotocols else None)
        socket.received.append(f"connect {path} {headers}")
        self.preview_sockets.append(socket)
        yield socket

    def info(self, sandbox_id: str) -> dict[str, Any]:
        box = self._get(sandbox_id, running=False)
        return {
            "id": sandbox_id,
            "pack": box["pack"],
            "state": box["state"],
            "createdAt": 1_800_000_000.0,
            "expiresAt": 1_800_005_400.0,
            "idleTimeoutS": 900,
            "previewBase": box["previewBase"],
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

    def run_hidden_tests(self, sandbox_id: str, files: dict[str, str]) -> dict[str, Any]:
        self._get(sandbox_id)
        self.hidden_runs.append(dict(files))
        return copy.deepcopy(self.hidden_report(files))

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
