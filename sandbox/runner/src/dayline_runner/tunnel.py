"""Reach a port inside a sandbox that has no network.

Sandboxes run with ``network_mode: none``, so nothing outside one can open a
TCP connection to its dev servers, and that stays true for the preview.
Instead each connection is a ``docker exec`` of ``socat STDIO
TCP:127.0.0.1:<port>`` inside the sandbox: its stdin and stdout, over the
Docker API socket, carry the connection's bytes. The exec runs without a
TTY so the bytes pass through untouched; Docker then frames its output
(8-byte headers per chunk, saying stdout or stderr), which
:class:`TunnelStream` strips.

:class:`SandboxNetwork` plugs tunnels into ``httpcore`` as a network
backend, so the preview proxy gets a real HTTP/1.1 client with keep-alive
pooling (a tunnel costs a Docker round trip to open) without any socket
code of its own: the URL's host is the sandbox id and its port is the port.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import struct
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpcore

_HEADER = struct.Struct(">BxxxL")
_STDOUT, _STDERR = 1, 2
MAX_STDERR_BYTES = 4096


class TunnelClosed(Exception):
    """The connection inside the sandbox could not be made or has ended."""


class TunnelStream:
    """One connection to a port in a sandbox, as an async byte stream."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._pending = b""
        self._closed = False
        # What socat said (e.g. "Connection refused"), to explain a failure.
        self.stderr = b""

    @classmethod
    async def open(cls, sock: socket.socket) -> TunnelStream:
        reader, writer = await asyncio.open_connection(sock=sock)
        return cls(reader, writer)

    async def read(self, max_bytes: int = 65536) -> bytes:
        """Up to ``max_bytes`` of the connection's data; ``b""`` once it ended."""
        while not self._pending:
            try:
                header = await self._reader.readexactly(_HEADER.size)
                kind, size = _HEADER.unpack(header)
                payload = await self._reader.readexactly(size)
            except (asyncio.IncompleteReadError, ConnectionError):
                return b""
            if kind == _STDOUT:
                self._pending = payload
            elif kind == _STDERR and len(self.stderr) < MAX_STDERR_BYTES:
                self.stderr += payload[: MAX_STDERR_BYTES - len(self.stderr)]
        data, self._pending = self._pending[:max_bytes], self._pending[max_bytes:]
        return data

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise TunnelClosed("The connection is closed")
        try:
            self._writer.write(data)
            await self._writer.drain()
        except ConnectionError as exc:
            raise TunnelClosed(str(exc)) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        with contextlib.suppress(Exception):
            await self._writer.wait_closed()

    def at_eof(self) -> bool:
        """Whether the other side hung up (with nothing left to read)."""
        return not self._pending and self._reader.at_eof()


Opener = Callable[[str, int], Awaitable[TunnelStream]]


class _NetworkStream(httpcore.AsyncNetworkStream):
    def __init__(self, tunnel: TunnelStream) -> None:
        self.tunnel = tunnel

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        try:
            return await asyncio.wait_for(self.tunnel.read(max_bytes), timeout)
        except TimeoutError as exc:
            raise httpcore.ReadTimeout(str(exc)) from exc

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        try:
            await asyncio.wait_for(self.tunnel.write(buffer), timeout)
        except TimeoutError as exc:
            raise httpcore.WriteTimeout(str(exc)) from exc
        except TunnelClosed as exc:
            raise httpcore.WriteError(str(exc)) from exc

    async def aclose(self) -> None:
        await self.tunnel.aclose()

    async def start_tls(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise httpcore.UnsupportedProtocol("Sandbox servers are plain HTTP")

    def get_extra_info(self, info: str) -> Any:
        # httpcore drops a pooled connection that turned readable while idle
        # (the server hung up), instead of sending a request into it.
        if info == "is_readable":
            return self.tunnel.at_eof()
        return None


class SandboxNetwork(httpcore.AsyncNetworkBackend):
    """``connect_tcp(sandbox_id, port)`` opens a tunnel into that sandbox."""

    def __init__(self, opener: Opener) -> None:
        self._opener = opener

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            tunnel = await asyncio.wait_for(self._opener(host, port), timeout)
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(str(exc)) from exc
        return _NetworkStream(tunnel)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.UnsupportedProtocol("Sandbox servers are reached by port")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
