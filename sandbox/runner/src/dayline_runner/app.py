"""HTTP + WebSocket API over :class:`SandboxManager`.

Only the Dayline API talks to this service, on a private network, and every
request must carry ``Authorization: Bearer <SANDBOX_RUNNER_SECRET>``. Run::

    uvicorn dayline_runner.app:create_app --factory --port 8100
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import docker
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from dayline_runner.config import Settings
from dayline_runner.manager import SandboxError, SandboxManager
from dayline_runner.packs import load_packs

log = logging.getLogger(__name__)


class CreateRequest(BaseModel):
    id: str
    pack: str
    files: dict[str, str] = Field(default_factory=dict)


class HiddenTestsRequest(BaseModel):
    # Test files by path (relative to the hidden-tests folder), for one run only.
    files: dict[str, str]


class WriteRequest(BaseModel):
    content: str
    # The version the editor loaded; "" = the file must not exist yet. Omit to overwrite.
    baseVersion: str | None = None  # noqa: N815 - wire format is camelCase


def _authorized(header: str | None, secret: str) -> bool:
    if not header or not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip().encode(), secret.encode())


def get_manager(request: Request) -> SandboxManager:
    result: SandboxManager = request.app.state.manager
    return result


def require_secret(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    if not _authorized(authorization, request.app.state.settings.secret):
        raise HTTPException(status_code=401, detail="Bad runner secret")


Manager = Annotated[SandboxManager, Depends(get_manager)]


def create_app(manager: SandboxManager | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass a manager; otherwise one is made from the
    environment on startup (Docker from ``DOCKER_HOST``)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.manager is None:
            cfg = app.state.settings
            app.state.manager = SandboxManager(docker.from_env(), cfg, load_packs(cfg.packs_dir))
            app.state.manager.start_background()
        yield
        app.state.manager.stop_background()

    app = FastAPI(title="Dayline sandbox runner", lifespan=lifespan)
    app.state.manager = manager
    app.state.settings = settings or Settings.from_env()

    auth = [Depends(require_secret)]

    @app.exception_handler(SandboxError)
    async def sandbox_error(_: Request, exc: SandboxError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/packs", dependencies=auth)
    def packs(m: Manager) -> list[dict[str, Any]]:
        return m.pack_statuses()

    @app.post("/sandboxes", status_code=201, dependencies=auth)
    def create(body: CreateRequest, m: Manager) -> dict[str, Any]:
        return m.create(body.id, body.pack, body.files)

    @app.get("/sandboxes/{sandbox_id}", dependencies=auth)
    def info(sandbox_id: str, m: Manager) -> dict[str, Any]:
        return m.info(sandbox_id)

    @app.post("/sandboxes/{sandbox_id}/resume", dependencies=auth)
    def resume(sandbox_id: str, m: Manager) -> dict[str, Any]:
        return m.resume(sandbox_id)

    @app.delete("/sandboxes/{sandbox_id}", status_code=204, dependencies=auth)
    def destroy(sandbox_id: str, m: Manager) -> None:
        m.destroy(sandbox_id)

    @app.get("/sandboxes/{sandbox_id}/files", dependencies=auth)
    def list_files(sandbox_id: str, m: Manager) -> list[dict[str, Any]]:
        return [
            {"path": e.path, "size": e.size, "version": e.version} for e in m.list_files(sandbox_id)
        ]

    @app.get("/sandboxes/{sandbox_id}/files/{path:path}", dependencies=auth)
    def read_file(sandbox_id: str, path: str, m: Manager) -> dict[str, Any]:
        return m.read_file(sandbox_id, path)

    @app.put("/sandboxes/{sandbox_id}/files/{path:path}", dependencies=auth)
    def write_file(sandbox_id: str, path: str, body: WriteRequest, m: Manager) -> dict[str, Any]:
        return m.write_file(sandbox_id, path, body.content, body.baseVersion)

    @app.get("/sandboxes/{sandbox_id}/snapshot", dependencies=auth)
    def snapshot(sandbox_id: str, m: Manager) -> dict[str, Any]:
        return m.snapshot(sandbox_id)

    @app.get("/sandboxes/{sandbox_id}/commands", dependencies=auth)
    def commands(sandbox_id: str, m: Manager) -> list[dict[str, Any]]:
        return [
            {"at": c.at, "exitCode": c.exit_code, "command": c.command}
            for c in m.commands(sandbox_id)
        ]

    @app.post("/sandboxes/{sandbox_id}/tests", dependencies=auth)
    def run_tests(sandbox_id: str, m: Manager) -> dict[str, Any]:
        return m.run_tests(sandbox_id).to_json()

    @app.post("/sandboxes/{sandbox_id}/hidden-tests", dependencies=auth)
    def run_hidden_tests(sandbox_id: str, body: HiddenTestsRequest, m: Manager) -> dict[str, Any]:
        return m.run_hidden_tests(sandbox_id, body.files).to_json()

    @app.websocket("/sandboxes/{sandbox_id}/pty")
    async def pty(ws: WebSocket, sandbox_id: str, cols: int = 80, rows: int = 24) -> None:
        """Binary frames carry terminal bytes both ways. Text frames from the
        client are JSON control messages: ``{"type": "resize", "cols", "rows"}``."""
        if not _authorized(ws.headers.get("authorization"), ws.app.state.settings.secret):
            await ws.close(code=1008)
            return
        m: SandboxManager = ws.app.state.manager
        await ws.accept()
        try:
            handle = await run_in_threadpool(m.open_pty, sandbox_id, cols, rows)
        except SandboxError as exc:
            # 4xxx: an application close code carrying the HTTP status.
            await ws.close(code=4000 + exc.status_code, reason=exc.message[:120])
            return

        async def pump_out() -> None:
            while data := await asyncio.to_thread(handle.recv):
                await ws.send_bytes(data)

        async def pump_in() -> None:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes"):
                    m.touch(sandbox_id)
                    await asyncio.to_thread(handle.send, message["bytes"])
                elif message.get("text"):
                    try:
                        control = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(control, dict) and control.get("type") == "resize":
                        await run_in_threadpool(
                            m.resize_pty,
                            handle,
                            int(control.get("cols") or cols),
                            int(control.get("rows") or rows),
                        )

        tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await run_in_threadpool(m.close_pty, handle)
            # RuntimeError: the client already closed it.
            with contextlib.suppress(RuntimeError):
                await ws.close(code=1000, reason="Shell exited")

    return app
