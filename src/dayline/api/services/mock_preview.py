"""A live session's dev servers and the browser preview of them.

Packs like ``rails`` and ``next-nest`` run dev servers in the sandbox (see
the runner's ``servers.py``). The browser sees them at

    /api/preview/<session id>/<token>/<port>/...

and this module forwards those requests, HTTP and WebSocket (hot reload),
to the runner's preview proxy. The browser never talks to the runner.

**Why a token in the path, and no cookie check.** The previewed app is
untrusted code (whatever the candidate, an assistant, or a generated
project wrote), served from Dayline's own origin. So every preview
response carries ``Content-Security-Policy: sandbox ...`` without
``allow-same-origin``: the browser runs the app in an opaque origin, where
it cannot read Dayline's pages, storage or cookies, nor call ``/api/*``
with the session. The flip side is that the browser sends no Dayline
cookie on the app's own requests either, so the URL itself is the
credential: ``<token>`` is random per session (the sandbox's preview base,
``mock_live.new_preview_base``), only handed out by the signed-in status endpoint, and
checked by the runner. An app in an opaque origin cannot use
``localStorage`` or ``document.cookie``; full-stack apps keep state on
their server.

Requests are rewritten toward what the app would see in the sandbox
(``Origin``/``Referer`` on ``localhost:<port>``, no browser cookies: they
are Dayline's, and the runner keeps the app's own in a per-sandbox jar),
and responses toward what is safe on Dayline's origin: redirects to
``localhost`` become relative, and headers that would act on the whole
origin (HSTS, ``Clear-Site-Data``, reporting) are dropped. The app's
``fetch`` calls are cross-origin from its opaque origin, so this module
answers their CORS preflights and allows them.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from dayline.adapters.sandbox import (
    PreviewSocket,
    SandboxClient,
    SandboxRequestError,
    SandboxUnavailable,
)
from dayline.api.context import AppContext
from dayline.api.services.mock_live import (
    PREVIEW_PREFIX,
    event,
    live_session,
    runner_errors,
    sandbox_client,
)
from dayline.models import MockEventKind

# The runner marks its own error answers (vs. the app's) with this header.
PREVIEW_ERROR_HEADER = "x-dayline-preview-error"
SERVER_ACTIONS = ("start", "stop", "restart")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
# The app runs sandboxed, in an opaque origin (see the module docstring).
SANDBOX_CSP = (
    "sandbox allow-scripts allow-forms allow-modals allow-popups "
    "allow-popups-to-escape-sandbox allow-downloads"
)
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_DROP_UPSTREAM = HOP_BY_HOP | {
    "host",
    "authorization",
    # Dayline's own (the session); the runner keeps the app's.
    "cookie",
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
}
# Response headers that would reach past the app's own path on Dayline's
# origin, or undo the sandboxing; ours replace some of them.
_DROP_DOWNSTREAM = HOP_BY_HOP | {
    # Our own server sets these.
    "date",
    "server",
    "strict-transport-security",
    "clear-site-data",
    "service-worker-allowed",
    "report-to",
    "reporting-endpoints",
    "nel",
    "x-frame-options",
    "cross-origin-embedder-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "access-control-expose-headers",
    "referrer-policy",
    "set-cookie",
    PREVIEW_ERROR_HEADER,
}
_LOCAL_ORIGIN = re.compile(
    r"^https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d+)?(?=[/?#]|$)", re.IGNORECASE
)
_ORIGIN = re.compile(r"^[a-z][a-z0-9+.-]*://[^/?#]*", re.IGNORECASE)


def preview_base(session_id: str, token: str) -> str | None:
    """The base a preview URL claims, or ``None`` if it is malformed."""
    if not _SESSION_ID.match(session_id) or not _TOKEN.match(token):
        return None
    return f"{PREVIEW_PREFIX}/{session_id}/{token}"


# -- the servers (signed-in endpoints) ------------------------------------------


def status(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """``{base, servers}``: where the preview lives (``None`` for a sandbox
    started before previews existed) and the pack's dev servers (empty for
    packs without any)."""
    live_session(ctx, session_id)
    sandbox = sandbox_client(ctx)
    with runner_errors():
        info = sandbox.info(session_id)
        servers = sandbox.servers(session_id) if info["state"] == "running" else []
    return {"base": info.get("previewBase"), "servers": servers}


def server_action(ctx: AppContext, session_id: str, name: str, action: str) -> dict[str, Any]:
    live_session(ctx, session_id)
    if action not in SERVER_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown server action {action!r}")
    with runner_errors():
        sandbox_client(ctx).server_action(session_id, name, action)
    event(ctx, session_id, MockEventKind.SERVER_ACTION, server=name, action=action)
    return status(ctx, session_id)


def server_logs(ctx: AppContext, session_id: str, name: str, since: int) -> dict[str, Any]:
    live_session(ctx, session_id)
    with runner_errors():
        return sandbox_client(ctx).server_logs(session_id, name, max(0, since))


def preview_reloaded(ctx: AppContext, session_id: str, server: str) -> None:
    """The candidate reloaded the preview (for the session record)."""
    live_session(ctx, session_id)
    event(ctx, session_id, MockEventKind.PREVIEW_RELOADED, server=server)


# Per server, for the assistant: the end of each log is what explains a crash.
ASSISTANT_LOG_LINES = 200


def server_logs_reader(sandbox: SandboxClient, session_id: str) -> Callable[[], str] | None:
    """The in-session assistant's view of the dev servers' logs (its
    ``Workspace.server_logs``), or ``None`` when the pack runs none (or the
    runner predates dev servers)."""
    try:
        if not sandbox.servers(session_id):
            return None
    except (SandboxUnavailable, SandboxRequestError):
        return None

    def read() -> str:
        try:
            parts = []
            for server in sandbox.servers(session_id):
                lines = sandbox.server_logs(session_id, server["name"], 0)["lines"]
                body = "\n".join(lines[-ASSISTANT_LOG_LINES:]) or "(no output)"
                parts.append(
                    f"== {server['name']} (port {server['port']}, {server['state']}) ==\n{body}"
                )
            return "\n\n".join(parts)
        except (SandboxUnavailable, SandboxRequestError) as exc:
            return f"Could not read the server logs: {exc}"

    return read


# -- header rewriting (pure) -----------------------------------------------------


def upstream_headers(headers: list[tuple[str, str]], port: int) -> list[tuple[str, str]]:
    """The browser's request headers as the app should see them."""
    local = f"http://localhost:{port}"
    out: list[tuple[str, str]] = []
    for name, value in headers:
        key = name.lower()
        if key in _DROP_UPSTREAM or key.startswith(("sec-fetch-", "x-dayline-")):
            # Sec-Fetch-* would read as cross-site (the app runs in an opaque
            # origin), which dev servers refuse for their assets.
            continue
        if key == "origin":
            out.append((name, local))
        elif key == "referer":
            out.append((name, _ORIGIN.sub(local, value, count=1)))
        else:
            out.append((name, value))
    if not any(name.lower() == "accept-encoding" for name, _ in out):
        # Otherwise the HTTP client's default would ask for gzip on its behalf.
        out.append(("accept-encoding", "identity"))
    return out


def _cors(origin: str | None) -> list[tuple[str, str]]:
    """Let the app's own page read the answer: its fetches, module scripts
    and fonts are CORS requests from the opaque origin (``Origin: null``)."""
    if not origin:
        return [("access-control-allow-origin", "*")]
    return [
        ("access-control-allow-origin", origin),
        ("access-control-allow-credentials", "true"),
        ("access-control-expose-headers", "*"),
        ("vary", "Origin"),
    ]


def browser_headers(headers: list[tuple[str, str]], origin: str | None) -> list[tuple[str, str]]:
    """The app's response headers as they may reach the browser. ``origin``
    is the request's ``Origin`` (``"null"`` from the sandboxed app)."""
    out: list[tuple[str, str]] = []
    for name, value in headers:
        key = name.lower()
        if key in _DROP_DOWNSTREAM:
            continue
        if key == "location":
            out.append((name, _LOCAL_ORIGIN.sub("", value, count=1) or "/"))
        else:
            out.append((name, value))
    return [
        *out,
        ("content-security-policy", SANDBOX_CSP),
        ("referrer-policy", "no-referrer"),
        *_cors(origin),
    ]


def preflight(request_headers: Any) -> Response:
    """Answer a CORS preflight for the app. The app would never see one (its
    page and its API share an origin); they only happen because the page
    runs in an opaque origin, so the preview answers them itself."""
    headers = dict(_cors(request_headers.get("origin")))
    headers["access-control-allow-methods"] = (
        request_headers.get("access-control-request-method") or "GET"
    )
    if requested := request_headers.get("access-control-request-headers"):
        headers["access-control-allow-headers"] = requested
    headers["access-control-max-age"] = "600"
    return Response(status_code=204, headers=headers)


def _wants_page(headers: Any) -> bool:
    dest = headers.get("sec-fetch-dest", "")
    return dest in ("document", "iframe") or (not dest and "text/html" in headers.get("accept", ""))


def error_page(status_code: int, detail: str, request_headers: Any) -> Response:
    """Why the preview could not be shown: a small page for a frame or tab,
    JSON for anything else. Sandboxed like the app."""
    headers = {
        "content-security-policy": SANDBOX_CSP,
        "cache-control": "no-store",
        **dict(_cors(request_headers.get("origin"))),
    }
    if not _wants_page(request_headers):
        return JSONResponse({"detail": detail}, status_code=status_code, headers=headers)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preview unavailable</title>
<style>
:root {{ color-scheme: light dark; --bg: #ffffff; --fg: #18181b; --muted: #71717a; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #09090b; --fg: #f4f4f5; --muted: #a1a1aa; }}
}}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg);
  color: var(--fg); font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 28rem; padding: 1.5rem; text-align: center; }}
h1 {{ font-size: 15px; font-weight: 600; margin: 0 0 0.375rem; }}
p {{ margin: 0; color: var(--muted); }}
</style></head>
<body><main><h1>The preview is not available</h1><p>{html.escape(detail)}</p></main></body>
</html>"""
    return HTMLResponse(page, status_code=status_code, headers=headers)


# -- proxying ------------------------------------------------------------------------


def _client_and_base(ctx: AppContext, session_id: str, token: str) -> tuple[SandboxClient, str]:
    base = preview_base(session_id, token)
    if base is None:
        raise SandboxRequestError(404, "No such preview")
    if ctx.sandbox is None:
        raise SandboxUnavailable("Live sessions need the sandbox runner (set SANDBOX_RUNNER_URL).")
    return ctx.sandbox, base


async def proxy_http(
    ctx: AppContext, request: Request, session_id: str, token: str, port: int, path: str
) -> Response:
    """Forward one preview request. ``path`` is the raw part after the port
    (``""`` or ``/...``)."""
    if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
        if preview_base(session_id, token) is None:
            return error_page(404, "No such preview", request.headers)
        return preflight(request.headers)
    has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
    try:
        sandbox, base = _client_and_base(ctx, session_id, token)
        upstream = await sandbox.preview(
            session_id,
            base,
            port,
            path,
            method=request.method,
            query=request.url.query,
            headers=upstream_headers(
                [(k.decode("latin-1"), v.decode("latin-1")) for k, v in request.headers.raw],
                port,
            ),
            body=request.stream() if has_body else None,
        )
    except SandboxUnavailable as exc:
        return error_page(503, str(exc), request.headers)
    except SandboxRequestError as exc:
        return error_page(exc.status_code, exc.detail, request.headers)

    if any(name.lower() == PREVIEW_ERROR_HEADER for name, _ in upstream.headers):
        raw = b"".join([chunk async for chunk in upstream.body])
        await upstream.aclose()
        try:
            detail = str(json.loads(raw).get("detail") or "The preview failed")
        except (ValueError, AttributeError):
            detail = "The preview failed"
        if upstream.status == 401:
            detail = "Dayline and the sandbox runner have different SANDBOX_RUNNER_SECRETs"
        return error_page(upstream.status, detail, request.headers)

    async def body() -> AsyncIterator[bytes]:
        # A dev server restarting mid-response just ends the body.
        with contextlib.suppress(Exception):
            async for chunk in upstream.body:
                yield chunk

    response = StreamingResponse(
        body(), status_code=upstream.status, background=BackgroundTask(upstream.aclose)
    )
    response.raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in browser_headers(upstream.headers, request.headers.get("origin"))
    ]
    return response


async def _pump(ws: WebSocket, upstream: PreviewSocket) -> None:
    """Copy messages both ways until either side closes."""

    async def downstream() -> None:
        async for message in upstream:
            if isinstance(message, bytes):
                await ws.send_bytes(message)
            else:
                await ws.send_text(message)

    async def to_upstream() -> None:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await upstream.send(message["bytes"])
            elif message.get("text") is not None:
                await upstream.send(message["text"])

    tasks = [asyncio.create_task(downstream()), asyncio.create_task(to_upstream())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def proxy_ws(
    ctx: AppContext, ws: WebSocket, session_id: str, token: str, port: int, path: str
) -> None:
    """Bridge a preview WebSocket (e.g. hot reload). The browser's socket is
    accepted only once the app accepted, with the subprotocol it chose."""
    offered = [
        p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()
    ]
    headers = upstream_headers(
        [(k.decode("latin-1"), v.decode("latin-1")) for k, v in ws.headers.raw], port
    )
    forwarded = [(k, v) for k, v in headers if k.lower() in ("origin", "user-agent")]
    try:
        sandbox, base = _client_and_base(ctx, session_id, token)
        async with sandbox.open_preview_socket(
            session_id,
            base,
            port,
            path,
            query=ws.url.query,
            headers=forwarded,
            subprotocols=offered,
        ) as upstream:
            await ws.accept(subprotocol=upstream.subprotocol)
            await _pump(ws, upstream)
            code = getattr(upstream, "close_code", None) or 1000
    except (SandboxUnavailable, SandboxRequestError):
        code = 1011
    with contextlib.suppress(RuntimeError):
        await ws.close(code=code if code not in (1005, 1006) else 1000)
