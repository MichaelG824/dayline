"""The preview proxy: HTTP and WebSocket from the runner to a dev server
inside a sandbox, through :mod:`tunnel`.

``/sandboxes/{id}/preview/{port}/{rest}`` reaches ``{base}/{port}/{rest}``
on the server listening on ``port``, where ``base`` is the sandbox's
preview base (set when it was created). The app serves itself under that
path (its ``$BASE_PATH``), so the URLs it generates are the browser-facing
ones as they are, and nothing here rewrites bodies.

Every request must carry the sandbox's preview base in
``X-Dayline-Preview-Base`` as well as the runner secret: the base holds an
unguessable token, and Dayline only forwards requests whose URL has it.

The server sees ``Host: localhost:<port>``, like a request made inside
the sandbox, and the cookies the runner keeps for the sandbox
(``cookies.py``) rather than any the browser sent; its ``Set-Cookie``
headers go into that jar instead of to the browser. Other browser-facing
concerns (origins, CORS, the sandboxing CSP) are the Dayline API's job.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast

import httpcore
from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from websockets.client import ClientProtocol
from websockets.exceptions import InvalidHandshake, ProtocolError
from websockets.frames import Frame, Opcode
from websockets.protocol import State
from websockets.typing import Subprotocol
from websockets.uri import parse_uri

from dayline_runner.cookies import CookieJars
from dayline_runner.tunnel import SandboxNetwork, TunnelStream

log = logging.getLogger(__name__)

PREVIEW_BASE_HEADER = "x-dayline-preview-base"
# On the runner's own error answers, so Dayline can tell them from the app's.
PREVIEW_ERROR_HEADER = "x-dayline-preview-error"
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
_DROP_REQUEST = HOP_BY_HOP | {"host", "authorization", "cookie", PREVIEW_BASE_HEADER}
# Uvicorn adds its own date and server; cookies stay in the jar.
_DROP_RESPONSE = HOP_BY_HOP | {"date", "server", "set-cookie"}
# Headers worth passing on a WebSocket handshake (the rest are the
# handshake's own, which the client protocol writes).
_WS_FORWARD = ("origin", "user-agent", "accept-language")
# Long enough for a first dev-server compile.
TIMEOUTS = {"connect": 30.0, "read": 300.0, "write": 60.0, "pool": 30.0}
MAX_WS_MESSAGE = 16 * 1024 * 1024

# (sandbox id, port) -> a socket connected to that port inside the sandbox.
SocketOpener = Callable[[str, int], Awaitable[TunnelStream]]


def raw_suffix(scope: Mapping[str, Any]) -> str:
    """The raw (still-encoded) path after ``/sandboxes/{id}/preview/{port}``:
    ``""`` or ``"/..."``. Raw, so the app gets the path as the browser sent it."""
    raw: bytes = scope.get("raw_path") or scope["path"].encode()
    parts = raw.split(b"/", 5)  # ["", "sandboxes", id, "preview", port, rest]
    return "/" + parts[5].decode("latin-1") if len(parts) > 5 else ""


def _error(detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"detail": detail}, status_code=status_code, headers={PREVIEW_ERROR_HEADER: "1"}
    )


def unreachable(port: int, exc: Exception) -> JSONResponse:
    log.info("Preview of port %s failed: %s", port, exc)
    return _error(
        f"Nothing is answering on port {port} in the sandbox. Is the server running?", 502
    )


class PreviewProxy:
    def __init__(self, open_tunnel: SocketOpener) -> None:
        self._open = open_tunnel
        self.cookies = CookieJars()
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=SandboxNetwork(open_tunnel),
            max_connections=64,
            max_keepalive_connections=16,
            keepalive_expiry=15.0,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()

    async def http(self, request: Request, sandbox_id: str, port: int, path: str) -> Response:
        """Forward ``request`` to ``path`` (base included) on ``port``."""
        headers = [
            (name, value)
            for name, value in request.headers.items()
            if name not in _DROP_REQUEST and not name.startswith("x-dayline-")
        ]
        headers.append(("host", f"localhost:{port}"))
        jar = self.cookies.jar(sandbox_id)
        if cookie := jar.header(path):
            headers.append(("cookie", cookie))
        if "content-length" not in request.headers and "transfer-encoding" in request.headers:
            headers.append(("transfer-encoding", "chunked"))
        query = request.url.query
        target = path + (f"?{query}" if query else "")
        upstream = httpcore.Request(
            request.method,
            httpcore.URL(scheme="http", host=sandbox_id, port=port, target=target),
            headers=headers,
            content=request.stream(),
            extensions={"timeout": TIMEOUTS},
        )
        try:
            response = await self._pool.handle_async_request(upstream)
        except (httpcore.ConnectError, httpcore.RemoteProtocolError, httpcore.ReadError) as exc:
            return unreachable(port, exc)
        except httpcore.TimeoutException:
            return _error(f"The server on port {port} took too long to answer", 504)

        for name, value in response.headers:
            if name.lower() == b"set-cookie":
                jar.store(value.decode("latin-1"), path)
        stream = cast(AsyncIterable[bytes], response.stream)

        async def body() -> AsyncIterator[bytes]:
            # A server that hangs up mid-body just ends the response.
            with contextlib.suppress(httpcore.ReadError, httpcore.RemoteProtocolError):
                async for chunk in stream:
                    yield chunk

        proxied = StreamingResponse(
            body(), status_code=response.status, background=BackgroundTask(response.aclose)
        )
        proxied.raw_headers = [
            (name.lower(), value)
            for name, value in response.headers
            if name.lower().decode() not in _DROP_RESPONSE
        ]
        return proxied

    async def websocket(self, ws: WebSocket, sandbox_id: str, port: int, path: str) -> None:
        """Bridge an (unaccepted) client WebSocket to the server's at ``path``.
        The client is accepted only once the server accepted, with the
        subprotocol the server chose."""
        try:
            tunnel = await self._open(sandbox_id, port)
        except Exception as exc:  # Docker refused the exec, or the sandbox stopped.
            log.info("Preview WebSocket to port %s failed: %s", port, exc)
            await ws.close(code=1011, reason="The sandbox is not reachable")
            return
        try:
            await self._bridge(ws, tunnel, port, path, self.cookies.jar(sandbox_id).header(path))
        finally:
            await tunnel.aclose()

    async def _bridge(
        self, ws: WebSocket, tunnel: TunnelStream, port: int, path: str, cookie: str | None
    ) -> None:
        query = ws.url.query
        offered = [
            Subprotocol(p.strip())
            for p in ws.headers.get("sec-websocket-protocol", "").split(",")
            if p.strip()
        ]
        protocol = ClientProtocol(
            parse_uri(f"ws://localhost:{port}{path}" + (f"?{query}" if query else "")),
            subprotocols=offered or None,
            max_size=MAX_WS_MESSAGE,
        )
        handshake = protocol.connect()
        for name in _WS_FORWARD:
            if value := ws.headers.get(name):
                handshake.headers[name] = value
        if cookie:
            handshake.headers["cookie"] = cookie
        protocol.send_request(handshake)
        lock = asyncio.Lock()

        async def flush() -> None:
            async with lock:
                for data in protocol.data_to_send():
                    if data:
                        await tunnel.write(data)

        await flush()
        while protocol.state is State.CONNECTING:
            data = await tunnel.read()
            if data:
                protocol.receive_data(data)
            else:
                protocol.receive_eof()
                break
        if protocol.state is not State.OPEN or protocol.handshake_exc is not None:
            exc = protocol.handshake_exc
            if isinstance(exc, InvalidHandshake) or exc is None:
                log.info("Preview WebSocket handshake on port %s failed: %s", port, exc)
            await ws.close(code=1011, reason="The server refused the WebSocket")
            return
        await ws.accept(subprotocol=protocol.subprotocol)

        async def downstream() -> None:
            fragments: list[bytes] = []
            text = False
            while True:
                data = await tunnel.read()
                if not data:
                    protocol.receive_eof()
                else:
                    protocol.receive_data(data)
                for event in protocol.events_received():
                    if not isinstance(event, Frame):
                        continue
                    if event.opcode in (Opcode.TEXT, Opcode.BINARY):
                        text, fragments = event.opcode is Opcode.TEXT, [bytes(event.data)]
                    elif event.opcode is Opcode.CONT:
                        fragments.append(bytes(event.data))
                    else:
                        continue  # Pings are answered by the protocol; closes end below.
                    if event.fin:
                        message = b"".join(fragments)
                        if text:
                            await ws.send_text(message.decode())
                        else:
                            await ws.send_bytes(message)
                await flush()
                if protocol.state is State.CLOSED or not data:
                    return

        async def upstream() -> None:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    code = int(message.get("code") or 1000)
                    sendable = 1000 <= code <= 4999 and code not in (1005, 1006)
                    protocol.send_close(code if sendable else 1000)
                    await flush()
                    return
                if message.get("text") is not None:
                    protocol.send_text(message["text"].encode())
                elif message.get("bytes") is not None:
                    protocol.send_binary(message["bytes"])
                await flush()

        tasks = [asyncio.create_task(downstream()), asyncio.create_task(upstream())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except ProtocolError:
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            code = protocol.close_code or 1000
            with contextlib.suppress(RuntimeError):
                await ws.close(code=code if code not in (1005, 1006) else 1000)
