"""Sandbox lifecycle on top of the Docker API.

One sandbox per mock-interview session: a container built from a language
pack image, plus a named volume holding ``/workspace``. Every container runs
with no network, a read-only root filesystem, no capabilities, no new
privileges, a non-root user, and CPU / memory / process limits.

Lifecycle:

- ``create`` starts a container and copies the template files in.
- A sandbox untouched for ``idle_timeout_s``, or older than ``hard_cap_s``, is
  **stopped**, not deleted: its files stay readable (``snapshot``) and an idle
  one can be resumed until the hard cap.
- Stopped sandboxes are deleted after ``retain_s``.
- Docker labels are the source of truth, so a restarted runner adopts the
  sandboxes that already exist instead of losing track of them.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import secrets
import shlex
import socket
import tarfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import docker
from docker.errors import APIError, BuildError, ImageNotFound
from docker.errors import NotFound as DockerNotFound
from docker.models.containers import Container

from dayline_runner.commands import (
    BASHRC,
    BASHRC_PATH,
    COMMAND_LOG_PATH,
    CommandRun,
    parse_command_log,
)
from dayline_runner.config import Settings
from dayline_runner.junit import TestReport, build_report, parse_junit
from dayline_runner.packs import JUNIT_PATH, Pack
from dayline_runner.workspace import (
    IGNORED_DIRS,
    MAX_FILE_BYTES,
    MAX_FILES,
    WORKSPACE,
    FileEntry,
    clean_path,
    content_version,
    file_tar,
    parse_listing,
    read_snapshot,
)

log = logging.getLogger(__name__)

LABEL = "dayline.sandbox"
LABEL_ID = "dayline.sandbox.id"
LABEL_PACK = "dayline.sandbox.pack"
LABEL_CREATED = "dayline.sandbox.created"
NAME_PREFIX = "dayline-sbx-"
SANDBOX_USER = "1000:1000"
BASE_ENV = {
    "HOME": "/tmp",
    "HISTFILE": "/tmp/.bash_history",
    "TERM": "xterm-256color",
    "LANG": "C.UTF-8",
}
# Plain output for the test panel; the terminal keeps colours.
TEST_ENV = {"NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1"}
MAX_JUNIT_BYTES = 4 * 1024 * 1024
MAX_COMMAND_LOG_BYTES = 1024 * 1024
REAP_INTERVAL_S = 30
# `timeout` exits 124 when the limit is hit, 137 when it had to SIGKILL.
_TIMEOUT_EXIT_CODES = (124, 137)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")

PackState = Literal["pending", "building", "ready", "failed"]


class SandboxError(Exception):
    """A request the runner refuses; ``status_code`` is the HTTP status."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SandboxNotFound(SandboxError):
    status_code = 404


class SandboxConflict(SandboxError):
    status_code = 409


class SandboxBusy(SandboxError):
    status_code = 429


class PackUnavailable(SandboxError):
    status_code = 503


@dataclass(slots=True)
class PtyHandle:
    """One interactive shell in a sandbox, attached over a raw socket."""

    sandbox_id: str
    exec_id: str
    sock: socket.socket
    pid_file: str

    def recv(self) -> bytes:
        try:
            return self.sock.recv(65536)
        except OSError:
            return b""

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)


def _validate_id(sandbox_id: str) -> str:
    if not _ID.match(sandbox_id):
        raise SandboxError(f"Invalid sandbox id {sandbox_id!r}")
    return sandbox_id


class SandboxManager:
    def __init__(
        self,
        client: docker.DockerClient,
        settings: Settings,
        packs: dict[str, Pack],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._settings = settings
        self._packs = packs
        self._clock = clock
        self._lock = threading.RLock()
        self._last_active: dict[str, float] = {}
        self._pack_state: dict[str, tuple[PackState, str | None]] = {
            name: ("pending", None) for name in packs
        }
        self._stop = threading.Event()

    # -- background work ---------------------------------------------------

    def start_background(self) -> None:
        threading.Thread(target=self.build_packs, name="pack-builder", daemon=True).start()
        threading.Thread(target=self._reap_loop, name="reaper", daemon=True).start()

    def stop_background(self) -> None:
        self._stop.set()

    def build_packs(self) -> None:
        """Build every pack image that does not exist yet (one at a time)."""
        for pack in self._packs.values():
            if self._stop.is_set():
                return
            try:
                self._client.images.get(pack.image)
            except ImageNotFound:
                self._pack_state[pack.name] = ("building", None)
                log.info("Building %s", pack.image)
                try:
                    self._client.images.build(path=str(pack.directory), tag=pack.image, rm=True)
                except (BuildError, APIError) as exc:
                    log.error("Building %s failed: %s", pack.image, exc)
                    self._pack_state[pack.name] = ("failed", str(exc))
                    continue
            self._pack_state[pack.name] = ("ready", None)

    def _reap_loop(self) -> None:
        while not self._stop.wait(REAP_INTERVAL_S):
            try:
                self.reap()
            except Exception:  # The loop must survive a Docker hiccup.
                log.exception("Reaping sandboxes failed")

    def reap(self) -> None:
        """Stop idle or over-limit sandboxes and delete long-stopped ones."""
        now = self._clock()
        s = self._settings
        names: set[str] = set()
        for container in self._client.containers.list(all=True, filters={"label": LABEL}):
            names.add(container.name)
            sandbox_id = container.labels.get(LABEL_ID, "")
            age = now - float(container.labels.get(LABEL_CREATED, "0"))
            if container.status == "running":
                # setdefault: a sandbox from before a runner restart counts as
                # active now rather than being stopped immediately.
                idle = now - self._last_active.setdefault(sandbox_id, now)
                if age > s.hard_cap_s or idle > s.idle_timeout_s:
                    log.info("Stopping sandbox %s (age %ds, idle %ds)", sandbox_id, age, idle)
                    container.stop(timeout=5)
            elif age > s.retain_s:
                log.info("Deleting sandbox %s", sandbox_id)
                self._remove(container)
        # Volumes whose container is gone (e.g. a crash mid-create).
        for volume in self._client.volumes.list(filters={"label": LABEL}):
            if volume.name not in names:
                try:
                    volume.remove(force=True)
                except APIError:
                    log.warning("Could not remove orphan volume %s", volume.name)

    # -- packs ---------------------------------------------------------------

    def pack_statuses(self) -> list[dict[str, Any]]:
        return [
            {
                "name": p.name,
                "displayName": p.display_name,
                "editorLanguage": p.editor_language,
                "state": self._pack_state[p.name][0],
                "error": self._pack_state[p.name][1],
            }
            for p in self._packs.values()
        ]

    def _ready_pack(self, name: str) -> Pack:
        pack = self._packs.get(name)
        if pack is None:
            raise SandboxError(f"Unknown language pack {name!r}")
        state, error = self._pack_state[name]
        if state == "failed":
            raise PackUnavailable(f"The {pack.display_name} image failed to build: {error}")
        if state != "ready":
            raise PackUnavailable(
                f"The {pack.display_name} image is still being built. Try again in a minute."
            )
        return pack

    # -- lookup --------------------------------------------------------------

    def touch(self, sandbox_id: str) -> None:
        self._last_active[sandbox_id] = self._clock()

    def _container(self, sandbox_id: str) -> Container:
        try:
            return self._client.containers.get(NAME_PREFIX + _validate_id(sandbox_id))
        except DockerNotFound as exc:
            raise SandboxNotFound(f"No sandbox {sandbox_id!r}") from exc

    def _running(self, sandbox_id: str) -> Container:
        container = self._container(sandbox_id)
        if container.status != "running":
            raise SandboxConflict("The sandbox is stopped")
        self.touch(sandbox_id)
        return container

    def _running_count(self) -> int:
        return len(self._client.containers.list(filters={"label": LABEL, "status": "running"}))

    def _info(self, container: Container) -> dict[str, Any]:
        created = float(container.labels.get(LABEL_CREATED, "0"))
        return {
            "id": container.labels.get(LABEL_ID),
            "pack": container.labels.get(LABEL_PACK),
            "state": "running" if container.status == "running" else "stopped",
            "createdAt": created,
            "expiresAt": created + self._settings.hard_cap_s,
            "idleTimeoutS": self._settings.idle_timeout_s,
        }

    def info(self, sandbox_id: str) -> dict[str, Any]:
        return self._info(self._container(sandbox_id))

    # -- lifecycle -----------------------------------------------------------

    def create(self, sandbox_id: str, pack_name: str, files: dict[str, str]) -> dict[str, Any]:
        _validate_id(sandbox_id)
        pack = self._ready_pack(pack_name)
        if len(files) > MAX_FILES:
            raise SandboxError(f"At most {MAX_FILES} files")
        encoded = {clean_path(path): content.encode() for path, content in files.items()}
        if any(len(content) > MAX_FILE_BYTES for content in encoded.values()):
            raise SandboxError(f"Files must be under {MAX_FILE_BYTES // 1024} KB")

        name = NAME_PREFIX + sandbox_id
        s = self._settings
        with self._lock:
            try:
                self._client.containers.get(name)
                raise SandboxConflict(f"Sandbox {sandbox_id!r} already exists")
            except DockerNotFound:
                pass
            if self._running_count() >= s.max_running:
                raise SandboxBusy(f"{s.max_running} sandboxes are already running. End one first.")
            labels = {
                LABEL: "1",
                LABEL_ID: sandbox_id,
                LABEL_PACK: pack.name,
                LABEL_CREATED: str(int(self._clock())),
            }
            self._client.volumes.create(name=name, labels=labels)
            try:
                container = self._client.containers.run(
                    pack.image,
                    command=["sleep", "infinity"],
                    name=name,
                    hostname="sandbox",
                    detach=True,
                    init=True,
                    labels=labels,
                    user=SANDBOX_USER,
                    working_dir=WORKSPACE,
                    environment=BASE_ENV,
                    network_mode="none",
                    read_only=True,
                    tmpfs={"/tmp": "size=256m"},
                    volumes={name: {"bind": WORKSPACE, "mode": "rw"}},
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges"],
                    nano_cpus=int(s.cpus * 1e9),
                    mem_limit=s.memory,
                    memswap_limit=s.memory,
                    pids_limit=s.pids_limit,
                    runtime=s.runtime,
                )
                # The rc file goes in alongside the template (see commands.py).
                setup = {BASHRC_PATH: BASHRC.encode(), COMMAND_LOG_PATH: b""}
                container.put_archive(WORKSPACE, file_tar({**encoded, **setup}))
            except Exception:
                self._remove_by_name(name)
                raise
            self.touch(sandbox_id)
            container.reload()
            return self._info(container)

    def resume(self, sandbox_id: str) -> dict[str, Any]:
        with self._lock:
            container = self._container(sandbox_id)
            if container.status != "running":
                info = self._info(container)
                if self._clock() >= info["expiresAt"]:
                    raise SandboxConflict("This sandbox reached its time limit")
                if self._running_count() >= self._settings.max_running:
                    raise SandboxBusy("Too many sandboxes are running. End one first.")
                container.start()
                container.reload()
            self.touch(sandbox_id)
            return self._info(container)

    def destroy(self, sandbox_id: str) -> None:
        try:
            container = self._container(sandbox_id)
        except SandboxNotFound:
            self._remove_by_name(NAME_PREFIX + sandbox_id)  # A stray volume.
            return
        self._remove(container)

    def _remove(self, container: Container) -> None:
        name = container.name
        with contextlib.suppress(DockerNotFound):
            container.remove(force=True)
        self._last_active.pop(container.labels.get(LABEL_ID, ""), None)
        self._remove_by_name(name)

    def _remove_by_name(self, name: str) -> None:
        with contextlib.suppress(DockerNotFound):
            self._client.containers.get(name).remove(force=True)
        with contextlib.suppress(DockerNotFound):
            self._client.volumes.get(name).remove(force=True)

    # -- files ---------------------------------------------------------------

    def _exec(
        self, container: Container, cmd: list[str], env: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        result = container.exec_run(
            cmd,
            user=SANDBOX_USER,
            workdir=WORKSPACE,
            environment={**BASE_ENV, **(env or {})},
        )
        return int(result.exit_code or 0), bytes(result.output or b"")

    def list_files(self, sandbox_id: str) -> list[FileEntry]:
        container = self._running(sandbox_id)
        prune: list[str] = []
        for name in sorted(IGNORED_DIRS):
            prune += ["-o", "-name", name] if prune else ["-name", name]
        find = ["find", ".", "(", *prune, ")", "-prune", "-o", "-type", "f"]
        _, stats = self._exec(container, [*find, "-printf", "%s %T@ %P\\0"])
        small = f"-{MAX_FILE_BYTES // 1024 + 1}k"
        hash_cmd = " ".join(shlex.quote(a) for a in [*find, "-size", small, "-print0"])
        _, hashes = self._exec(container, ["sh", "-c", f"{hash_cmd} | xargs -0 -r sha1sum -z"])
        return parse_listing(stats, hashes)

    def _size(self, container: Container, path: str) -> int | None:
        """Size of a regular file, or ``None`` if there is none."""
        code, output = self._exec(
            container, ["find", f"./{path}", "-maxdepth", "0", "-type", "f", "-printf", "%s"]
        )
        return int(output) if code == 0 and output else None

    def _version(self, container: Container, path: str) -> str:
        """The file's version, or ``""`` if there is no such file."""
        size = self._size(container, path)
        if size is None:
            return ""
        if size > MAX_FILE_BYTES:
            return f"large-{size}"
        code, output = self._exec(container, ["sha1sum", "--", f"./{path}"])
        return output[:40].decode() if code == 0 else ""

    def read_file(self, sandbox_id: str, path: str) -> dict[str, Any]:
        path = clean_path(path)
        container = self._running(sandbox_id)
        size = self._size(container, path)
        if size is None:
            raise SandboxNotFound(f"No file {path!r}")
        if size > MAX_FILE_BYTES:
            raise SandboxError(f"{path} is too large to open ({size // 1024} KB)")
        code, content = self._exec(container, ["cat", "--", f"./{path}"])
        if code != 0:
            raise SandboxNotFound(f"No file {path!r}")
        try:
            text = content.decode()
        except UnicodeDecodeError as exc:
            raise SandboxError(f"{path} is not a text file") from exc
        # Hash what was actually read, so the version always matches the text.
        return {"path": path, "content": text, "version": content_version(content)}

    def write_file(
        self, sandbox_id: str, path: str, content: str, base_version: str | None
    ) -> dict[str, Any]:
        """Write a file. With ``base_version`` the write only happens if the file
        is unchanged since that version (``""`` means it must not exist yet)."""
        path = clean_path(path)
        data = content.encode()
        if len(data) > MAX_FILE_BYTES:
            raise SandboxError(f"Files must be under {MAX_FILE_BYTES // 1024} KB")
        container = self._running(sandbox_id)
        if base_version is not None and self._version(container, path) != base_version:
            raise SandboxConflict(f"{path} changed since it was opened")
        try:
            container.put_archive(WORKSPACE, file_tar({path: data}))
        except APIError as exc:
            raise SandboxError(f"Could not write {path}: {exc.explanation}") from exc
        return {"path": path, "version": content_version(data)}

    def snapshot(self, sandbox_id: str) -> dict[str, Any]:
        """Every text file in the workspace. Works on stopped sandboxes too."""
        container = self._container(sandbox_id)
        stream, _ = container.get_archive(WORKSPACE)
        try:
            files, skipped = read_snapshot(stream)
        except ValueError as exc:
            raise SandboxError(str(exc)) from exc
        return {"files": files, "skipped": skipped}

    def commands(self, sandbox_id: str) -> list[CommandRun]:
        """Commands typed in the terminal, oldest first. Works once stopped."""
        container = self._container(sandbox_id)
        try:
            stream, _ = container.get_archive(f"{WORKSPACE}/{COMMAND_LOG_PATH}")
        except DockerNotFound:
            return []
        data = bytearray()
        for chunk in stream:
            data.extend(chunk)
            if len(data) > MAX_COMMAND_LOG_BYTES:
                break
        with tarfile.open(fileobj=io.BytesIO(bytes(data)), mode="r:") as tar:
            member = next((m for m in tar if m.isreg()), None)
            raw = tar.extractfile(member) if member else None
            text = raw.read(MAX_COMMAND_LOG_BYTES).decode(errors="replace") if raw else ""
        return parse_command_log(text)

    # -- tests ---------------------------------------------------------------

    def run_tests(self, sandbox_id: str) -> TestReport:
        container = self._running(sandbox_id)
        pack = self._packs.get(container.labels.get(LABEL_PACK, ""))
        if pack is None:
            raise SandboxError("This sandbox's language pack no longer exists")
        script = f"rm -f {JUNIT_PATH}; exec {pack.test_cmd}"
        cmd = ["timeout", "-k", "5", str(pack.test_timeout_s), "sh", "-c", script]
        started = time.monotonic()
        exit_code, output = self._exec(container, cmd, env=TEST_ENV)
        duration = time.monotonic() - started
        timed_out = exit_code in _TIMEOUT_EXIT_CODES

        text = output.decode(errors="replace")
        code, xml = self._exec(container, ["head", "-c", str(MAX_JUNIT_BYTES), JUNIT_PATH])
        cases = None
        if code == 0 and xml:
            try:
                cases = parse_junit(xml)
            except ValueError as exc:
                text += f"\n[dayline] {exc}"
        if timed_out:
            text += f"\n[dayline] Tests were stopped after {pack.test_timeout_s} seconds."
        self.touch(sandbox_id)
        return build_report(
            cases, exit_code=exit_code, output=text, duration_s=duration, timed_out=timed_out
        )

    # -- terminal ------------------------------------------------------------

    def open_pty(self, sandbox_id: str, cols: int, rows: int) -> PtyHandle:
        container = self._running(sandbox_id)
        api = self._client.api
        pid_file = f"/tmp/.dayline-pty-{secrets.token_hex(6)}"
        # `exec` keeps the pid, so the shell can be hung up when the socket closes.
        rcfile = f"{WORKSPACE}/{BASHRC_PATH}"
        cmd = ["sh", "-c", f"echo $$ > {pid_file}; exec bash --rcfile {rcfile} -i"]
        exec_id = api.exec_create(
            container.id,
            cmd,
            stdin=True,
            tty=True,
            user=SANDBOX_USER,
            workdir=WORKSPACE,
            environment=BASE_ENV,
        )["Id"]
        raw = api.exec_start(exec_id, socket=True, tty=True)
        sock: socket.socket = getattr(raw, "_sock", raw)
        handle = PtyHandle(sandbox_id=sandbox_id, exec_id=exec_id, sock=sock, pid_file=pid_file)
        self.resize_pty(handle, cols, rows)
        return handle

    def resize_pty(self, handle: PtyHandle, cols: int, rows: int) -> None:
        cols, rows = max(10, min(cols, 500)), max(4, min(rows, 200))
        # The shell may not be up yet; the next resize applies.
        with contextlib.suppress(APIError):
            self._client.api.exec_resize(handle.exec_id, height=rows, width=cols)

    def close_pty(self, handle: PtyHandle) -> None:
        with contextlib.suppress(OSError):
            handle.sock.close()
        try:
            container = self._container(handle.sandbox_id)
            if container.status == "running":
                hangup = f"kill -HUP $(cat {handle.pid_file}) 2>/dev/null; rm -f {handle.pid_file}"
                self._exec(container, ["sh", "-c", hangup])
        except (SandboxError, APIError):
            pass
