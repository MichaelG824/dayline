"""A live session's dev servers and the browser preview of them. Logic
lives in ``services/mock_preview.py``.

The ``/api/preview/...`` routes skip the sign-in gate on purpose: the app
they serve runs in an opaque origin that never sends Dayline's cookie, so
the unguessable token in the path is the credential (see the service).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import mock_preview as service

router = APIRouter()

PREVIEW = "/api/preview/{session_id}/{token}/{port}"
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class ReloadedRequest(BaseModel):
    server: str


def _rest(raw_path: bytes) -> str:
    """The raw (still-encoded) path after the port: ``""`` or ``"/..."``.
    Raw, so an encoded slash or space reaches the app as the browser sent it."""
    parts = raw_path.split(b"/", 6)  # ["", "api", "preview", id, token, port, rest]
    return "/" + parts[6].decode("latin-1") if len(parts) > 6 else ""


@router.get("/api/mock/sessions/{session_id}/preview")
def preview_status(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.status(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/preview/reloaded", status_code=204)
def preview_reloaded(session_id: str, body: ReloadedRequest, ctx: ContextDep) -> None:
    service.preview_reloaded(ctx, session_id, body.server)


@router.post("/api/mock/sessions/{session_id}/servers/{name}/{action}")
def server_action(session_id: str, name: str, action: str, ctx: ContextDep) -> dict[str, Any]:
    return service.server_action(ctx, session_id, name, action)


@router.get("/api/mock/sessions/{session_id}/servers/{name}/logs")
def server_logs(session_id: str, name: str, ctx: ContextDep, since: int = 0) -> dict[str, Any]:
    return service.server_logs(ctx, session_id, name, since)


@router.api_route(PREVIEW, methods=METHODS, include_in_schema=False)
@router.api_route(PREVIEW + "/{path:path}", methods=METHODS, include_in_schema=False)
async def preview(
    session_id: str, token: str, port: int, request: Request, ctx: ContextDep
) -> Response:
    path = _rest(request.scope.get("raw_path") or request.url.path.encode())
    return await service.proxy_http(ctx, request, session_id, token, port, path)


@router.websocket(PREVIEW)
@router.websocket(PREVIEW + "/{path:path}")
async def preview_socket(
    ws: WebSocket, session_id: str, token: str, port: int, ctx: ContextDep
) -> None:
    path = _rest(ws.scope.get("raw_path") or ws.url.path.encode())
    await service.proxy_ws(ctx, ws, session_id, token, port, path)
