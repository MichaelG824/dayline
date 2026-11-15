"""Language packs: one folder per language under ``sandbox/packs/<name>/``.

Each pack is a ``Dockerfile`` plus a ``pack.toml``::

    name = "python"
    display_name = "Python 3.12"
    editor_language = "python"        # CodeMirror language id for the editor
    test_cmd = "python -m pytest -q --junitxml={junit}"
    test_timeout_s = 60
    # Optional: runs only the test files in {hidden} (staged rounds' hidden tests).
    hidden_test_cmd = "python -m pytest -q --junitxml={junit} {hidden}"
    # Optional: workspace files that must stay executable (globs, e.g. "bin/*").
    executables = ["bin/*"]
    # Optional: folders (by name, at any depth) kept out of the file tree and
    # snapshots, on top of workspace.IGNORED_DIRS: build output, logs, databases.
    ignore = ["tmp", "log"]
    # Optional: the sandbox's memory limit, when the runner default (1g) is
    # too small for the pack's dev servers plus a test run.
    memory = "1536m"

    # Optional: the dependencies a project may use (see deps.py). Sandboxes
    # have no network, so this is everything installed in the image, and
    # the pack must prove it: each one is checked against the pack's own
    # lockfile when the pack loads.
    [dependencies]
    manager = "npm"                   # or "bundler"
    allowed = { next = "16.4.6", react = "19.3.1" }

    # Optional: dev servers (servers.py), each previewable in the browser.
    [[servers]]
    name = "web"
    command = "cd web && next dev --port $PORT --hostname 127.0.0.1"
    port = 3000
    ready_path = ""                   # GET $BASE_PATH + this until it answers (omit: the port)
    ready_timeout_s = 120
    base_path = true                  # false: served from "/" (e.g. a JSON API); $BASE_PATH is ""

Every test command writes JUnit XML to ``{junit}``, so one parser
(``junit.py``) reads results for every language. Adding a language means
adding a folder, not code.

The image tag includes a hash of the folder's files, so editing a pack
rebuilds its image and an unchanged pack is never rebuilt.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dayline_runner.deps import DependencyManifest, load_manifest

# Where each test run writes its JUnit XML inside the sandbox (on the tmpfs).
JUNIT_PATH = "/tmp/dayline-junit.xml"
# Where hidden test files go for one run, relative to /workspace. Inside the
# ignored ".dayline" folder, so they never show in the file tree or a snapshot.
HIDDEN_TESTS_DIR = ".dayline/hidden"

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_SERVER_NAME = re.compile(r"^[a-z][a-z0-9-]{0,15}$")
_MEMORY = re.compile(r"^[1-9][0-9]{0,5}[mg]$")
DEFAULT_TEST_TIMEOUT_S = 60
MAX_TEST_TIMEOUT_S = 300
DEFAULT_READY_TIMEOUT_S = 90
MAX_READY_TIMEOUT_S = 600
MAX_SERVERS = 4
# Ports a dev server may use: unprivileged (the sandbox user cannot bind below 1024).
MIN_PORT, MAX_PORT = 1024, 65535


class PackError(ValueError):
    """A pack folder is missing a file or has an invalid ``pack.toml``."""


@dataclass(frozen=True, slots=True)
class ServerSpec:
    """A dev server the runner supervises inside the sandbox. It runs
    ``command`` with ``$PORT`` and ``$BASE_PATH`` (the path the preview serves
    it under, so the app can generate links that work through the proxy)."""

    name: str
    command: str
    port: int
    # GET $BASE_PATH + this until anything answers ("" = the app's root);
    # None = wait for the port to accept connections.
    ready_path: str | None = None
    ready_timeout_s: int = DEFAULT_READY_TIMEOUT_S
    autostart: bool = True
    # False: the server knows nothing of the preview path and serves from
    # "/"; the proxy strips the path off instead. Fine for a JSON API, not
    # for pages whose links would point outside the preview.
    base_path: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "port": self.port, "readyPath": self.ready_path}


@dataclass(frozen=True, slots=True)
class Pack:
    name: str
    display_name: str
    editor_language: str
    test_cmd: str
    test_timeout_s: int
    directory: Path
    image: str
    # None when the pack cannot run hidden tests.
    hidden_test_cmd: str | None = None
    executables: tuple[str, ...] = ()
    ignore: frozenset[str] = frozenset()
    # Docker memory limit ("1536m"); None = the runner's default.
    memory: str | None = None
    dependencies: DependencyManifest | None = None
    servers: tuple[ServerSpec, ...] = field(default=())

    def is_executable(self, path: str) -> bool:
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in self.executables)

    def server(self, name: str) -> ServerSpec | None:
        return next((s for s in self.servers if s.name == name), None)


def pack_digest(directory: Path) -> str:
    """A short hash of every file in the pack folder (names and contents)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _servers(raw: Any, where: Path) -> tuple[ServerSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_SERVERS:
        raise PackError(f"{where}: [[servers]] must be a list of at most {MAX_SERVERS}")
    servers: list[ServerSpec] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise PackError(f"{where}: each [[servers]] entry must be a table")
        name, command, port = entry.get("name"), entry.get("command"), entry.get("port")
        if not isinstance(name, str) or not _SERVER_NAME.match(name):
            raise PackError(f"{where}: server name {name!r} must be lowercase letters and dashes")
        if not isinstance(command, str) or not command.strip():
            raise PackError(f"{where}: server {name} needs a command")
        if not isinstance(port, int) or not MIN_PORT <= port <= MAX_PORT:
            raise PackError(f"{where}: server {name} port must be {MIN_PORT}-{MAX_PORT}")
        ready_path = entry.get("ready_path")
        if ready_path is not None and not (
            isinstance(ready_path, str) and (ready_path == "" or ready_path.startswith("/"))
        ):
            raise PackError(f"{where}: server {name} ready_path must be empty or start with /")
        timeout = entry.get("ready_timeout_s", DEFAULT_READY_TIMEOUT_S)
        if not isinstance(timeout, int) or not 1 <= timeout <= MAX_READY_TIMEOUT_S:
            raise PackError(f"{where}: server {name} ready_timeout_s must be 1-600")
        autostart, base_path = entry.get("autostart", True), entry.get("base_path", True)
        if not isinstance(autostart, bool) or not isinstance(base_path, bool):
            raise PackError(f"{where}: server {name} autostart/base_path must be true or false")
        servers.append(
            ServerSpec(name, command, port, ready_path, timeout, autostart, base_path)
        )
    names = [s.name for s in servers]
    ports = [s.port for s in servers]
    if len(set(names)) != len(names) or len(set(ports)) != len(ports):
        raise PackError(f"{where}: server names and ports must be unique")
    return tuple(servers)


def _executables(raw: Any, where: Path) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(p, str) and p for p in raw):
        raise PackError(f"{where}: executables must be a list of path globs")
    return tuple(raw)


def _ignore(raw: Any, where: Path) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or not all(
        isinstance(name, str) and name and "/" not in name and name not in (".", "..")
        for name in raw
    ):
        raise PackError(f"{where}: ignore must be a list of folder names")
    return frozenset(raw)


def load_pack(directory: Path) -> Pack:
    toml_path = directory / "pack.toml"
    if not toml_path.is_file() or not (directory / "Dockerfile").is_file():
        raise PackError(f"{directory} needs both a Dockerfile and a pack.toml")
    try:
        data = tomllib.loads(toml_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise PackError(f"{toml_path}: {exc}") from exc

    name = data.get("name")
    if not isinstance(name, str) or not _NAME.match(name) or name != directory.name:
        raise PackError(f"{toml_path}: name must match the folder name {directory.name!r}")
    test_cmd = data.get("test_cmd")
    if not isinstance(test_cmd, str) or "{junit}" not in test_cmd:
        raise PackError(f"{toml_path}: test_cmd must write JUnit XML to {{junit}}")
    hidden_cmd = data.get("hidden_test_cmd")
    if hidden_cmd is not None and not (
        isinstance(hidden_cmd, str) and "{junit}" in hidden_cmd and "{hidden}" in hidden_cmd
    ):
        raise PackError(f"{toml_path}: hidden_test_cmd must use both {{junit}} and {{hidden}}")
    timeout = data.get("test_timeout_s", DEFAULT_TEST_TIMEOUT_S)
    if not isinstance(timeout, int) or not 1 <= timeout <= MAX_TEST_TIMEOUT_S:
        raise PackError(f"{toml_path}: test_timeout_s must be 1-{MAX_TEST_TIMEOUT_S}")
    memory = data.get("memory")
    if memory is not None and not (isinstance(memory, str) and _MEMORY.match(memory)):
        raise PackError(f'{toml_path}: memory must look like "1536m" or "2g"')
    try:
        dependencies = (
            load_manifest(data["dependencies"], directory) if "dependencies" in data else None
        )
    except ValueError as exc:
        raise PackError(f"{toml_path}: {exc}") from exc

    return Pack(
        name=name,
        display_name=str(data.get("display_name") or name),
        editor_language=str(data.get("editor_language") or ""),
        test_cmd=test_cmd.replace("{junit}", JUNIT_PATH),
        test_timeout_s=timeout,
        directory=directory,
        image=f"dayline-pack-{name}:{pack_digest(directory)}",
        hidden_test_cmd=(
            hidden_cmd.replace("{junit}", JUNIT_PATH).replace("{hidden}", HIDDEN_TESTS_DIR)
            if hidden_cmd
            else None
        ),
        executables=_executables(data.get("executables"), toml_path),
        ignore=_ignore(data.get("ignore"), toml_path),
        memory=memory,
        dependencies=dependencies,
        servers=_servers(data.get("servers"), toml_path),
    )


def load_packs(packs_dir: Path) -> dict[str, Pack]:
    """Every pack under ``packs_dir``, by name."""
    if not packs_dir.is_dir():
        raise PackError(f"Packs folder {packs_dir} does not exist")
    packs = [load_pack(d) for d in sorted(packs_dir.iterdir()) if d.is_dir()]
    return {p.name: p for p in packs}
