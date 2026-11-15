"""Dev servers inside a sandbox: start, stop, restart, readiness, and logs.

A pack declares its servers in ``pack.toml`` (see packs.py). Each one runs
as the sandbox user via ``docker exec``, in its own session and process
group (``setsid``) so stopping it stops every process it started, with ``$PORT``
and ``$BASE_PATH`` (the path the preview serves it under) in its
environment. Its output goes to a pseudo-terminal: programs line-buffer
their logs for a terminal (Ruby holds piped output back) and stderr arrives
in order with stdout. Its process-group id goes to a pid file on the tmpfs, so a
stop works even after the runner restarted and lost track of the process,
and a stopped-and-resumed sandbox never finds a stale one.

The runner keeps the tail of each server's output in memory
(:class:`LogBuffer`), with ANSI colours and carriage-return redraws
removed. Logs are untrusted text from the sandbox and are capped.

Readiness: a server is ``ready`` once its port answers (or, with
``ready_path``, once an HTTP GET there gets any response). Probes run
inside the sandbox with ``socat`` because the sandbox has no network the
runner could reach.
"""

from __future__ import annotations

import codecs
import contextlib
import logging
import re
import shlex
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from docker.errors import APIError
from docker.errors import NotFound as DockerNotFound
from docker.models.containers import Container

from dayline_runner.packs import Pack, ServerSpec

log = logging.getLogger(__name__)

ServerState = Literal["stopped", "starting", "ready", "exited"]

MAX_LOG_LINES = 1000
MAX_LINE_CHARS = 2000
PROBE_INTERVAL_S = 1.0
STOP_GRACE_S = 5
# CSI (colours, cursor moves), OSC (titles, links), charset picks, and the
# other two-character escapes (e.g. "ESC c", the reset `node --watch` sends).
_ANSI = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()*+].|\x1b[0-~]"
)


def pid_file(name: str) -> str:
    return f"/tmp/dayline-server-{name}.pid"


class LogBuffer:
    """The tail of a server's output, as numbered lines. Thread-safe."""

    def __init__(self, max_lines: int = MAX_LOG_LINES) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        # The number of the oldest line still kept (lines are numbered from 0).
        self._first = 0
        self._partial = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._lock = threading.Lock()

    def _push(self, line: str) -> None:
        if len(self._lines) == self._lines.maxlen:
            self._first += 1
        self._lines.append(line[:MAX_LINE_CHARS])

    def write(self, data: bytes) -> None:
        text = self._decoder.decode(data)
        with self._lock:
            pieces = (self._partial + text).split("\n")
            self._partial = pieces.pop()
            for piece in pieces:
                self._push(_clean(piece))
            # A runaway line without a newline is still capped.
            if len(self._partial) > MAX_LINE_CHARS * 4:
                self._push(_clean(self._partial))
                self._partial = ""

    def note(self, message: str) -> None:
        """A line from the runner itself, e.g. why a server stopped."""
        with self._lock:
            if self._partial:
                self._push(_clean(self._partial))
                self._partial = ""
            self._push(f"[dayline] {message}")

    def read(self, since: int = 0) -> dict[str, Any]:
        """Lines numbered ``since`` and later: ``{lines, next, truncated}``.
        ``truncated`` means some lines after ``since`` were already dropped."""
        with self._lock:
            end = self._first + len(self._lines)
            start = max(since, self._first)
            lines = list(self._lines)[start - self._first :] if start < end else []
            return {"lines": lines, "next": end, "truncated": since < self._first}


def _clean(line: str) -> str:
    # A progress bar redraws with "\r": only the last drawing is real.
    line = line.rstrip("\r").rsplit("\r", 1)[-1]
    return _ANSI.sub("", line)


@dataclass(slots=True)
class ServerRun:
    spec: ServerSpec
    log: LogBuffer = field(default_factory=LogBuffer)
    state: ServerState = "stopped"
    exit_code: int | None = None
    started_at: float | None = None
    ready_at: float | None = None
    # Bumped on every start/stop, so a stale reader or probe thread can tell
    # it no longer owns the run.
    generation: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            **self.spec.to_json(),
            "state": self.state,
            "exitCode": self.exit_code,
            "startedAt": self.started_at,
            "readyAt": self.ready_at,
        }


ExecFn = Callable[[Container, list[str]], tuple[int, bytes]]


class DevServers:
    """Every sandbox's dev servers. The manager owns one and calls it with
    running containers; Docker access goes through ``exec_fn`` (a plain
    ``docker exec`` as the sandbox user) and the low-level API client."""

    def __init__(
        self,
        api: Any,
        exec_fn: ExecFn,
        exec_env: dict[str, str],
        user: str,
        workdir: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._api = api
        self._exec = exec_fn
        self._env = exec_env
        self._user = user
        self._workdir = workdir
        self._clock = clock
        self._runs: dict[tuple[str, str], ServerRun] = {}
        self._lock = threading.Lock()

    def _run(self, sandbox_id: str, spec: ServerSpec) -> ServerRun:
        with self._lock:
            run = self._runs.get((sandbox_id, spec.name))
            if run is None or run.spec != spec:
                run = self._runs[(sandbox_id, spec.name)] = ServerRun(spec=spec)
            return run

    def _bump(self, run: ServerRun) -> int:
        with self._lock:
            run.generation += 1
            return run.generation

    def _owns(self, run: ServerRun, generation: int) -> bool:
        with self._lock:
            return run.generation == generation

    # -- reads ---------------------------------------------------------------

    def statuses(self, sandbox_id: str, pack: Pack) -> list[dict[str, Any]]:
        return [self._run(sandbox_id, spec).to_json() for spec in pack.servers]

    def logs(self, sandbox_id: str, spec: ServerSpec, since: int) -> dict[str, Any]:
        return self._run(sandbox_id, spec).log.read(since)

    # -- lifecycle -------------------------------------------------------------

    def start(self, sandbox_id: str, container: Container, spec: ServerSpec, base: str) -> None:
        """(Re)start a server. Returns once it is launched; readiness and
        output are followed on background threads."""
        run = self._run(sandbox_id, spec)
        self._kill(container, spec)
        generation = self._bump(run)
        run.state, run.exit_code = "starting", None
        run.started_at, run.ready_at = self._clock(), None
        run.log.note(f"Starting {spec.name}: {spec.command}")
        # setsid only starts a new session without forking when it is not a
        # group leader, hence the background job; the outer shell stays
        # outside the server's group and reports its exit code.
        inner = f"echo $$ > {pid_file(spec.name)}\n{spec.command}"
        script = f"setsid sh -c {shlex.quote(inner)} & wait $!"
        env = {**self._env, "PORT": str(spec.port), "BASE_PATH": base}
        try:
            exec_id = self._api.exec_create(
                container.id,
                ["sh", "-c", script],
                tty=True,
                user=self._user,
                workdir=self._workdir,
                environment=env,
            )["Id"]
            raw = self._api.exec_start(exec_id, tty=True, socket=True)
            output: socket.socket = getattr(raw, "_sock", raw)
        except APIError as exc:
            run.state = "exited"
            run.log.note(f"Could not start {spec.name}: {exc}")
            return
        threading.Thread(
            target=self._follow,
            args=(run, generation, exec_id, output),
            name=f"server-{sandbox_id}-{spec.name}",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._probe_until_ready,
            args=(run, generation, container, base),
            name=f"probe-{sandbox_id}-{spec.name}",
            daemon=True,
        ).start()

    def stop(self, sandbox_id: str, container: Container, spec: ServerSpec) -> None:
        run = self._run(sandbox_id, spec)
        self._bump(run)
        was_running = run.state in ("starting", "ready")
        self._kill(container, spec)
        run.state, run.ready_at = "stopped", None
        if was_running:
            run.log.note(f"Stopped {spec.name}")

    def forget(self, sandbox_id: str, reason: str | None = None) -> None:
        """The sandbox stopped (or is gone): its servers are no longer running."""
        with self._lock:
            runs = [run for (sid, _), run in self._runs.items() if sid == sandbox_id]
            for run in runs:
                run.generation += 1
        for run in runs:
            if run.state in ("starting", "ready") and reason:
                run.log.note(reason)
            run.state, run.ready_at = "stopped", None

    def drop(self, sandbox_id: str) -> None:
        """The sandbox was deleted: forget its servers and their logs."""
        self.forget(sandbox_id)
        with self._lock:
            for key in [k for k in self._runs if k[0] == sandbox_id]:
                del self._runs[key]

    def _kill(self, container: Container, spec: ServerSpec) -> None:
        """Stop the server's whole process group: SIGTERM, then SIGKILL after
        a grace period."""
        pid = pid_file(spec.name)
        ticks = int(STOP_GRACE_S / 0.25)
        script = (
            f"p=$(cat {pid} 2>/dev/null) || exit 0; rm -f {pid}; "
            f'case "$p" in ""|*[!0-9]*) exit 0;; esac; '
            f"kill -TERM -$p 2>/dev/null || exit 0; "
            f"i=0; while [ $i -lt {ticks} ]; do kill -0 -$p 2>/dev/null || exit 0; "
            f"sleep 0.25; i=$((i + 1)); done; kill -KILL -$p 2>/dev/null; exit 0"
        )
        with contextlib.suppress(APIError, DockerNotFound):
            self._exec(container, ["sh", "-c", script])

    # -- background ------------------------------------------------------------

    def _follow(self, run: ServerRun, generation: int, exec_id: str, output: socket.socket) -> None:
        with output:
            while True:
                try:
                    chunk = output.recv(65536)
                except TimeoutError:
                    continue  # The Docker client's read timeout: just a quiet server.
                except OSError:
                    break  # The stream dies with the container.
                if not chunk:
                    break
                run.log.write(chunk)
        if not self._owns(run, generation):
            return
        try:
            code = self._api.exec_inspect(exec_id).get("ExitCode")
        except (APIError, DockerNotFound):
            code = None
        if not self._owns(run, generation):
            return
        run.state, run.exit_code, run.ready_at = "exited", code, None
        run.log.note(f"{run.spec.name} exited" + (f" with code {code}" if code is not None else ""))

    def _probe_until_ready(
        self, run: ServerRun, generation: int, container: Container, base: str
    ) -> None:
        spec = run.spec
        deadline = time.monotonic() + spec.ready_timeout_s
        warned = False
        while self._owns(run, generation) and run.state == "starting":
            remaining = max(5.0, deadline - time.monotonic())
            try:
                ok = self._probe(container, spec, base, remaining)
            except (APIError, DockerNotFound):
                return
            if ok and self._owns(run, generation) and run.state == "starting":
                run.state, run.ready_at = "ready", self._clock()
                run.log.note(f"{spec.name} is ready on port {spec.port}")
                return
            if not warned and time.monotonic() > deadline:
                warned = True
                run.log.note(
                    f"{spec.name} is still not answering on port {spec.port} "
                    f"after {spec.ready_timeout_s}s"
                )
            time.sleep(PROBE_INTERVAL_S)

    def _probe(self, container: Container, spec: ServerSpec, base: str, timeout: float) -> bool:
        target = f"TCP:127.0.0.1:{spec.port},connect-timeout=2"
        if spec.ready_path is None:
            code, _ = self._exec(container, ["socat", "-u", "/dev/null", target])
            return code == 0
        # shut-none: some servers (Puma) hang up on a half-closed request.
        request = (
            f"GET {base + spec.ready_path or '/'} HTTP/1.1\r\nHost: localhost:{spec.port}\r\n"
            "Connection: close\r\n\r\n"
        )
        cmd = (
            f"printf %s {shlex.quote(request)} | "
            f"socat -T {int(timeout)} STDIO {target},shut-none | head -c 12"
        )
        code, output = self._exec(container, ["sh", "-c", cmd])
        return output.startswith(b"HTTP/")
