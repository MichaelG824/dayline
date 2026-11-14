"""Workspace file helpers that need no Docker: path checks, tar building and
reading, and parsing the file listing the sandbox prints.

Paths are always relative to ``/workspace`` and POSIX-style. Anything
produced inside a sandbox (listings, archives) is untrusted input.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass

WORKSPACE = "/workspace"
SANDBOX_UID = 1000

# Never shown in the file tree or saved in a snapshot. ".dayline" holds the
# runner's own files (see commands.py).
IGNORED_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".venv",
        ".vite",
        ".dayline",
    }
)
MAX_FILE_BYTES = 512 * 1024
MAX_PATH_CHARS = 240
# A snapshot stops reading once this much has come out of the sandbox.
MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024
MAX_FILES = 2000


class WorkspacePathError(ValueError):
    """A path that is absolute, escapes the workspace, or is otherwise unusable."""


def clean_path(path: str) -> str:
    """``path`` as a normalised workspace-relative path, or raise."""
    if not path or len(path) > MAX_PATH_CHARS or "\0" in path or "\\" in path:
        raise WorkspacePathError(f"Invalid path {path!r}")
    if path.startswith("/"):
        raise WorkspacePathError("Paths are relative to the workspace")
    normalised = posixpath.normpath(path)
    parts = normalised.split("/")
    if normalised in (".", "") or ".." in parts:
        raise WorkspacePathError(f"Path {path!r} leaves the workspace")
    if any(part in IGNORED_DIRS for part in parts[:-1]):
        raise WorkspacePathError(f"Path {path!r} is inside an ignored folder")
    return normalised


def is_ignored(path: str) -> bool:
    return any(part in IGNORED_DIRS for part in path.split("/"))


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    size: int
    # The sha1 of the contents (mtime-size for files too big to hash). Used
    # for optimistic concurrency: a save from a stale editor is rejected,
    # not silently merged.
    version: str


def content_version(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def parse_listing(stats: bytes, hashes: bytes) -> list[FileEntry]:
    """Join ``find -printf '%s %T@ %P\\0'`` (size, mtime, path) with
    ``sha1sum -z`` output (``<sha>  ./<path>\\0``) into file entries."""
    sha_by_path: dict[str, str] = {}
    for record in hashes.split(b"\0"):
        digest, _, raw = record.partition(b"  ")
        if len(digest) == 40 and raw.startswith(b"./"):
            sha_by_path[raw[2:].decode(errors="replace")] = digest.decode()
    entries: list[FileEntry] = []
    for record in stats.split(b"\0"):
        if not record:
            continue
        try:
            size, mtime, raw_path = record.decode().split(" ", 2)
            path = clean_path(raw_path)
        except (UnicodeDecodeError, ValueError):
            continue  # Unrepresentable names are skipped, not fatal.
        version = sha_by_path.get(raw_path) or f"{mtime}-{size}"
        entries.append(FileEntry(path=path, size=int(size), version=version))
    entries.sort(key=lambda e: e.path)
    return entries[:MAX_FILES]


def file_tar(files: dict[str, bytes]) -> bytes:
    """A tar of ``files`` (and their parent folders) owned by the sandbox user,
    for ``put_archive`` into ``/workspace``."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        folders: set[str] = set()
        for path in files:
            parent = posixpath.dirname(path)
            while parent and parent not in folders:
                folders.add(parent)
                parent = posixpath.dirname(parent)
        for folder in sorted(folders):
            info = tarfile.TarInfo(folder)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = SANDBOX_UID
            tar.addfile(info)
        for path, content in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = 0o644
            info.uid = info.gid = SANDBOX_UID
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def read_snapshot(
    chunks: Iterable[bytes], root: str = "workspace"
) -> tuple[dict[str, str], list[str]]:
    """Text files from a ``get_archive`` stream of ``/workspace``.

    Returns ``(files, skipped)``: ``skipped`` lists paths left out because they
    are binary, too large, or past the size budget. Symlinks and other
    non-regular entries are ignored.
    """
    data = bytearray()
    for chunk in chunks:
        data.extend(chunk)
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise ValueError("The workspace is too large to save")
    files: dict[str, str] = {}
    skipped: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(bytes(data)), mode="r:") as tar:
        for member in tar:
            name = member.name
            if name == root or not name.startswith(root + "/") or not member.isreg():
                continue
            path = name[len(root) + 1 :]
            if is_ignored(path):
                continue
            extracted = tar.extractfile(member)
            if member.size > MAX_FILE_BYTES or extracted is None or len(files) >= MAX_FILES:
                skipped.append(path)
                continue
            try:
                files[path] = extracted.read().decode()
            except UnicodeDecodeError:
                skipped.append(path)
    return dict(sorted(files.items())), sorted(skipped)
