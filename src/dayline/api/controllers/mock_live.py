"""Live mock sessions: start one, work in its sandbox (files, tests,
terminal), end it. Logic lives in ``services/mock_live.py``."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from dayline.adapters.sandbox import SandboxUnavailable, TerminalConnection
from dayline.api.auth import websocket_auth_problem
from dayline.api.context import ContextDep
from dayline.api.services import mock as mock_service
from dayline.api.services import mock_live as service

router = APIRouter()


class StartRequest(BaseModel):
    templateId: str
    questionId: str | None = None
    rubricId: str | None = None
    guidelineId: str | None = None


class WriteRequest(BaseModel):
    content: str
    # The version the editor loaded; "" for a new file. Omit to overwrite.
    baseVersion: str | None = None


@router.get("/api/mock/live")
def availability(ctx: ContextDep) -> dict[str, Any]:
    return service.availability(ctx)


@router.post("/api/mock/live/sessions", status_code=201)
def start_session(body: StartRequest, ctx: ContextDep) -> dict[str, Any]:
    session_id = service.start_session(
        ctx, body.templateId, body.questionId, body.rubricId, body.guidelineId
    )
    return mock_service.get_session(ctx, session_id)


@router.get("/api/mock/sessions/{session_id}/sandbox")
def sandbox_status(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.sandbox_status(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/resume")
def resume(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.resume(ctx, session_id)


@router.get("/api/mock/sessions/{session_id}/files")
def list_files(session_id: str, ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_files(ctx, session_id)


@router.get("/api/mock/sessions/{session_id}/files/{path:path}")
def read_file(session_id: str, path: str, ctx: ContextDep) -> dict[str, Any]:
    return service.read_file(ctx, session_id, path)


@router.put("/api/mock/sessions/{session_id}/files/{path:path}")
def write_file(session_id: str, path: str, body: WriteRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.write_file(ctx, session_id, path, body.content, body.baseVersion)


@router.post("/api/mock/sessions/{session_id}/tests")
def run_tests(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    """Run the tests in the sandbox. Slow: up to the pack's test timeout."""
    return service.run_tests(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/end")
def end_session(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    service.end_session(ctx, session_id)
    return mock_service.get_session(ctx, session_id)


async def _pipe(ws: WebSocket, terminal: TerminalConnection) -> None:
    """Copy frames both ways until either side closes."""

    async def downstream() -> None:
        async for message in terminal:
            if isinstance(message, bytes):
                await ws.send_bytes(message)
            else:
                await ws.send_text(message)

    async def upstream() -> None:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await terminal.send(message["bytes"])
            elif message.get("text") is not None:
                await terminal.send(message["text"])

    tasks = [asyncio.create_task(downstream()), asyncio.create_task(upstream())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@router.websocket("/api/mock/sessions/{session_id}/terminal")
async def terminal(
    ws: WebSocket, session_id: str, ctx: ContextDep, cols: int = 80, rows: int = 24
) -> None:
    """The sandbox shell, proxied from the runner. Binary frames are terminal
    bytes; text frames from the browser are control JSON (resize). Closes
    with 4000 + an HTTP status when the session or sandbox can't be used."""
    problem = websocket_auth_problem(ws)
    if problem is not None:
        await ws.close(code=1008, reason=problem)
        return
    await ws.accept()
    code, reason = 1000, "Shell exited"
    try:
        opener = await run_in_threadpool(service.open_terminal, ctx, session_id, cols, rows)
        async with opener as connection:
            await _pipe(ws, connection)
            # The runner's own close (e.g. 4409 when the sandbox stopped).
            code = getattr(connection, "close_code", None) or code
            reason = getattr(connection, "close_reason", None) or reason
    except HTTPException as exc:
        code, reason = 4000 + exc.status_code, str(exc.detail)
    except SandboxUnavailable as exc:
        code, reason = 4503, str(exc)
    # Close reasons are capped at 123 bytes by the protocol.
    with contextlib.suppress(RuntimeError):
        await ws.close(code=code, reason=reason.encode()[:120].decode(errors="ignore"))
