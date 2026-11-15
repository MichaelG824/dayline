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

A pack can declare dev servers (``servers.py``): they start when the
sandbox does (and when it resumes), and the preview proxy (``preview.py``)
reaches them through exec tunnels (``tunnel.py``), so the no-network rule
holds for them too.
"""

from __future__ import annotations

import contextlib
import hmac
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
    DAYLINE_DIR,
    CommandRun,
    parse_command_log,
)
from dayline_runner.config import Settings
from dayline_runner.deps import project_problems
from dayline_runner.junit import TestReport, build_report, parse_junit
from dayline_runner.packs import HIDDEN_TESTS_DIR, JUNIT_PATH, Pack, ServerSpec
from dayline_runner.servers import DevServers
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
# The path the preview serves the sandbox's servers under (see preview.py).
LABEL_PREVIEW_BASE = "dayline.sandbox.preview-base"
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
_PREVIEW_BASE = re.compile(r"^(/[A-Za-z0-9_-]{1,64}){1,6}$")

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
        """The next output, or ``b""`` once the shell is gone. The socket
        keeps the Docker client's read timeout (60s by default); that only
        means the shell was quiet, so keep waiting."""
        while True:
            try:
                return self.sock.recv(65536)
            except TimeoutError:
                continue
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
        self.servers = DevServers(
            client.api,
            self._exec,
            exec_env=BASE_ENV,
            user=SANDBOX_USER,
            workdir=WORKSPACE,
            clock=clock,
        )

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
                    self.servers.forget(sandbox_id, "The sandbox stopped (idle or out of time)")
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
                "servers": [spec.to_json() for spec in p.servers],
                "dependencies": p.dependencies.to_json() if p.dependencies else None,
            }
            for p in self._packs.values()
        ]

    def dependency_problems(self, pack_name: str, files: dict[str, str]) -> list[str]:
        """Why ``files`` use dependencies the pack does not have (empty = fine)."""
        pack = self._packs.get(pack_name)
        if pack is None:
            raise SandboxError(f"Unknown language pack {pack_name!r}")
        return project_problems(pack.dependencies, files) if pack.dependencies else []

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
            "previewBase": container.labels.get(LABEL_PREVIEW_BASE),
        }

    def info(self, sandbox_id: str) -> dict[str, Any]:
        return self._info(self._container(sandbox_id))

    # -- lifecycle -----------------------------------------------------------

    def create(
        self,
        sandbox_id: str,
        pack_name: str,
        files: dict[str, str],
        preview_base: str | None = None,
    ) -> dict[str, Any]:
        """Start a sandbox with ``files``. ``preview_base`` is the path its dev
        servers are previewed under (it holds the caller's unguessable token);
        without one they are served from ``/``."""
        _validate_id(sandbox_id)
        pack = self._ready_pack(pack_name)
        if len(files) > MAX_FILES:
            raise SandboxError(f"At most {MAX_FILES} files")
        encoded = {
            clean_path(path, pack.ignore): content.encode() for path, content in files.items()
        }
        if any(len(content) > MAX_FILE_BYTES for content in encoded.values()):
            raise SandboxError(f"Files must be under {MAX_FILE_BYTES // 1024} KB")
        if preview_base is not None and not _PREVIEW_BASE.match(preview_base):
            raise SandboxError("Invalid preview base")
        if problems := self.dependency_problems(pack.name, files):
            raise SandboxError("Dependencies the sandbox does not have: " + "; ".join(problems))

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
            if preview_base:
                labels[LABEL_PREVIEW_BASE] = preview_base
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
                    mem_limit=pack.memory or s.memory,
                    memswap_limit=pack.memory or s.memory,
                    pids_limit=s.pids_limit,
                    runtime=s.runtime,
                )
                # The rc file goes in alongside the template (see commands.py).
                setup = {BASHRC_PATH: BASHRC.encode(), COMMAND_LOG_PATH: b""}
                container.put_archive(
                    WORKSPACE, file_tar({**encoded, **setup}, pack.is_executable)
                )
            except Exception:
                self._remove_by_name(name)
                raise
            self.touch(sandbox_id)
            container.reload()
        self._autostart(container, pack)
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
                self._autostart(container, self._pack_of(container))
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
        sandbox_id = container.labels.get(LABEL_ID, "")
        self._last_active.pop(sandbox_id, None)
        self.servers.drop(sandbox_id)
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
        ignored = self._pack_of(container).ignore
        prune: list[str] = []
        for name in sorted(IGNORED_DIRS | ignored):
            prune += ["-o", "-name", name] if prune else ["-name", name]
        find = ["find", ".", "(", *prune, ")", "-prune", "-o", "-type", "f"]
        _, stats = self._exec(container, [*find, "-printf", "%s %T@ %P\\0"])
        small = f"-{MAX_FILE_BYTES // 1024 + 1}k"
        hash_cmd = " ".join(shlex.quote(a) for a in [*find, "-size", small, "-print0"])
        _, hashes = self._exec(container, ["sh", "-c", f"{hash_cmd} | xargs -0 -r sha1sum -z"])
        return parse_listing(stats, hashes, ignored)

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
        container = self._running(sandbox_id)
        path = clean_path(path, self._pack_of(container).ignore)
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
        is unchanged since that version (``""`` means it must not exist yet).

        The bytes arrive in the ignored ``.dayline`` folder and a process in
        the sandbox copies them into place, so the write happens inside it:
        dev-server file watchers (inotify) then see an ordinary in-place
        save, which under gVisor they would not for a file changed from
        outside the sandbox."""
        data = content.encode()
        if len(data) > MAX_FILE_BYTES:
            raise SandboxError(f"Files must be under {MAX_FILE_BYTES // 1024} KB")
        container = self._running(sandbox_id)
        path = clean_path(path, self._pack_of(container).ignore)
        if base_version is not None and self._version(container, path) != base_version:
            raise SandboxConflict(f"{path} changed since it was opened")
        staged = f"{DAYLINE_DIR}/incoming/{secrets.token_hex(8)}"
        mode = "755" if self._pack_of(container).is_executable(path) else "644"
        try:
            container.put_archive(WORKSPACE, file_tar({staged: data}))
        except APIError as exc:
            raise SandboxError(f"Could not write {path}: {exc.explanation}") from exc
        # A new file gets the pack's mode; an existing one keeps its own.
        script = (
            'mkdir -p -- "$(dirname -- "$2")"'
            ' && { [ -e "$2" ] || { : > "$2" && chmod "$3" "$2"; }; }'
            ' && cat -- "$1" > "$2"; code=$?; rm -f -- "$1"; exit $code'
        )
        code, output = self._exec(container, ["sh", "-c", script, "sh", staged, f"./{path}", mode])
        if code != 0:
            detail = output.decode(errors="replace").strip().splitlines()
            raise SandboxError(f"Could not write {path}: {detail[-1] if detail else code}")
        return {"path": path, "version": content_version(data)}

    def snapshot(self, sandbox_id: str) -> dict[str, Any]:
        """Every text file in the workspace. Works on stopped sandboxes too."""
        container = self._container(sandbox_id)
        stream, _ = container.get_archive(WORKSPACE)
        try:
            files, skipped = read_snapshot(stream, extra=self._pack_of(container).ignore)
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

    def _pack_of(self, container: Container) -> Pack:
        pack = self._packs.get(container.labels.get(LABEL_PACK, ""))
        if pack is None:
            raise SandboxError("This sandbox's language pack no longer exists")
        return pack

    def _run_test_cmd(
        self, sandbox_id: str, container: Container, pack: Pack, cmd: str
    ) -> TestReport:
        script = f"rm -f {JUNIT_PATH}; exec {cmd}"
        timeout = ["timeout", "-k", "5", str(pack.test_timeout_s), "sh", "-c", script]
        started = time.monotonic()
        exit_code, output = self._exec(container, timeout, env=TEST_ENV)
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

    def run_tests(self, sandbox_id: str) -> TestReport:
        container = self._running(sandbox_id)
        pack = self._pack_of(container)
        return self._run_test_cmd(sandbox_id, container, pack, pack.test_cmd)

    def run_hidden_tests(self, sandbox_id: str, files: dict[str, str]) -> TestReport:
        """Run test files the candidate never sees (a staged round's hidden
        tests) against the workspace. They are copied into the ignored
        ``.dayline/hidden`` folder for this run only and deleted afterwards."""
        container = self._running(sandbox_id)
        pack = self._pack_of(container)
        if pack.hidden_test_cmd is None:
            raise SandboxError(f"The {pack.display_name} pack cannot run hidden tests")
        if not files:
            raise SandboxError("No hidden test files")
        encoded = {
            f"{HIDDEN_TESTS_DIR}/{clean_path(path)}": content.encode()
            for path, content in files.items()
        }
        if any(len(content) > MAX_FILE_BYTES for content in encoded.values()):
            raise SandboxError(f"Files must be under {MAX_FILE_BYTES // 1024} KB")
        clear = ["rm", "-rf", "--", HIDDEN_TESTS_DIR]
        self._exec(container, clear)
        try:
            container.put_archive(WORKSPACE, file_tar(encoded))
            return self._run_test_cmd(sandbox_id, container, pack, pack.hidden_test_cmd)
        finally:
            self._exec(container, clear)

    # -- dev servers and the preview -----------------------------------------

    def _autostart(self, container: Container, pack: Pack) -> None:
        sandbox_id = container.labels.get(LABEL_ID, "")
        for spec in pack.servers:
            if spec.autostart:
                self.servers.start(sandbox_id, container, spec, self._server_base(container, spec))

    @staticmethod
    def _server_base(container: Container, spec: ServerSpec) -> str:
        """The server's ``$BASE_PATH``: where the preview serves it."""
        base = container.labels.get(LABEL_PREVIEW_BASE)
        return f"{base}/{spec.port}" if base and spec.base_path else ""

    def _spec(self, container: Container, name: str) -> ServerSpec:
        pack = self._pack_of(container)
        spec = pack.server(name)
        if spec is None:
            raise SandboxNotFound(f"The {pack.display_name} pack has no server {name!r}")
        return spec

    def server_statuses(self, sandbox_id: str) -> list[dict[str, Any]]:
        """``[{name, port, readyPath, state, exitCode, startedAt, readyAt}]``;
        every server reads as stopped while the sandbox is."""
        container = self._container(sandbox_id)
        if container.status != "running":
            self.servers.forget(sandbox_id)
        return self.servers.statuses(sandbox_id, self._pack_of(container))

    def server_action(self, sandbox_id: str, name: str, action: str) -> list[dict[str, Any]]:
        """``start``, ``stop`` or ``restart`` a server; returns every status."""
        container = self._running(sandbox_id)
        spec = self._spec(container, name)
        if action == "stop":
            self.servers.stop(sandbox_id, container, spec)
        elif action in ("start", "restart"):
            self.servers.start(sandbox_id, container, spec, self._server_base(container, spec))
        else:
            raise SandboxError(f"Unknown server action {action!r}")
        return self.servers.statuses(sandbox_id, self._pack_of(container))

    def server_logs(self, sandbox_id: str, name: str, since: int) -> dict[str, Any]:
        """``{lines, next, truncated}``: output from line ``since`` on."""
        container = self._container(sandbox_id)
        return self.servers.logs(sandbox_id, self._spec(container, name), max(0, since))

    def preview_path(self, sandbox_id: str, port: int, base: str, suffix: str) -> str:
        """The path to request from the server on ``port`` for the preview URL
        ``.../{port}{suffix}``, once ``base`` is shown to be the sandbox's
        preview base. Only the pack's server ports can be previewed."""
        container = self._running(sandbox_id)
        expected = container.labels.get(LABEL_PREVIEW_BASE) or ""
        if not hmac.compare_digest(base.encode(), expected.encode()):
            raise SandboxNotFound("No such preview")
        spec = next((s for s in self._pack_of(container).servers if s.port == port), None)
        if spec is None:
            raise SandboxNotFound(f"Nothing is previewable on port {port}")
        return f"{self._server_base(container, spec)}{suffix}" or "/"

    def open_port(self, sandbox_id: str, port: int) -> socket.socket:
        """A connection to ``port`` inside the sandbox (see tunnel.py): a
        ``socat`` exec whose stdin/stdout carry the bytes, Docker-framed."""
        container = self._running(sandbox_id)
        api = self._client.api
        exec_id = api.exec_create(
            container.id,
            ["socat", "STDIO", f"TCP:127.0.0.1:{port},connect-timeout=5"],
            stdin=True,
            user=SANDBOX_USER,
            workdir=WORKSPACE,
        )["Id"]
        raw = api.exec_start(exec_id, socket=True)
        sock: socket.socket = getattr(raw, "_sock", raw)
        # The Docker client's read timeout would end a quiet keep-alive connection.
        sock.settimeout(None)
        return sock

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
