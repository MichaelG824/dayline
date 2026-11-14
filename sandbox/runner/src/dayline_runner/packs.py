"""Language packs: one folder per language under ``sandbox/packs/<name>/``.

Each pack is a ``Dockerfile`` plus a ``pack.toml``::

    name = "python"
    display_name = "Python 3.12"
    editor_language = "python"        # CodeMirror language id for the editor
    test_cmd = "python -m pytest -q --junitxml={junit}"
    test_timeout_s = 60

Every ``test_cmd`` writes JUnit XML to ``{junit}``, so one parser
(``junit.py``) reads results for every language. Adding a language means
adding a folder, not code.

The image tag includes a hash of the folder's files, so editing a pack
rebuilds its image and an unchanged pack is never rebuilt.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Where each test run writes its JUnit XML inside the sandbox (on the tmpfs).
JUNIT_PATH = "/tmp/dayline-junit.xml"

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
DEFAULT_TEST_TIMEOUT_S = 60
MAX_TEST_TIMEOUT_S = 300


class PackError(ValueError):
    """A pack folder is missing a file or has an invalid ``pack.toml``."""


@dataclass(frozen=True, slots=True)
class Pack:
    name: str
    display_name: str
    editor_language: str
    test_cmd: str
    test_timeout_s: int
    directory: Path
    image: str


def pack_digest(directory: Path) -> str:
    """A short hash of every file in the pack folder (names and contents)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


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
    timeout = data.get("test_timeout_s", DEFAULT_TEST_TIMEOUT_S)
    if not isinstance(timeout, int) or not 1 <= timeout <= MAX_TEST_TIMEOUT_S:
        raise PackError(f"{toml_path}: test_timeout_s must be 1-{MAX_TEST_TIMEOUT_S}")

    return Pack(
        name=name,
        display_name=str(data.get("display_name") or name),
        editor_language=str(data.get("editor_language") or ""),
        test_cmd=test_cmd.replace("{junit}", JUNIT_PATH),
        test_timeout_s=timeout,
        directory=directory,
        image=f"dayline-pack-{name}:{pack_digest(directory)}",
    )


def load_packs(packs_dir: Path) -> dict[str, Pack]:
    """Every pack under ``packs_dir``, by name."""
    if not packs_dir.is_dir():
        raise PackError(f"Packs folder {packs_dir} does not exist")
    packs = [load_pack(d) for d in sorted(packs_dir.iterdir()) if d.is_dir()]
    return {p.name: p for p in packs}
