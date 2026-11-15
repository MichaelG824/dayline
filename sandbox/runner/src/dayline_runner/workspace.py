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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

WORKSPACE = "/workspace"
SANDBOX_UID = 1000

# Never shown in the file tree or saved in a snapshot. ".dayline" holds the
# runner's own files (see commands.py). A pack can add its own (pack.toml's
# ``ignore``, e.g. Rails' tmp/ and log/); the functions below take them as
# ``extra``.
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
# Reading stops past this much archive, ignored folders (build caches,
# databases) included, which are read past rather than kept.
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 2000


class WorkspacePathError(ValueError):
    """A path that is absolute, escapes the workspace, or is otherwise unusable."""


def clean_path(path: str, extra: frozenset[str] = frozenset()) -> str:
    """``path`` as a normalised workspace-relative path, or raise."""
    if not path or len(path) > MAX_PATH_CHARS or "\0" in path or "\\" in path:
        raise WorkspacePathError(f"Invalid path {path!r}")
    if path.startswith("/"):
        raise WorkspacePathError("Paths are relative to the workspace")
    normalised = posixpath.normpath(path)
    parts = normalised.split("/")
    if normalised in (".", "") or ".." in parts:
        raise WorkspacePathError(f"Path {path!r} leaves the workspace")
    if any(part in IGNORED_DIRS or part in extra for part in parts[:-1]):
        raise WorkspacePathError(f"Path {path!r} is inside an ignored folder")
    return normalised


def is_ignored(path: str, extra: frozenset[str] = frozenset()) -> bool:
    return any(part in IGNORED_DIRS or part in extra for part in path.split("/"))


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


def parse_listing(
    stats: bytes, hashes: bytes, extra: frozenset[str] = frozenset()
) -> list[FileEntry]:
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
            path = clean_path(raw_path, extra)
        except (UnicodeDecodeError, ValueError):
            continue  # Unrepresentable names are skipped, not fatal.
        version = sha_by_path.get(raw_path) or f"{mtime}-{size}"
        entries.append(FileEntry(path=path, size=int(size), version=version))
    entries.sort(key=lambda e: e.path)
    return entries[:MAX_FILES]


def file_tar(
    files: dict[str, bytes], executable: Callable[[str], bool] = lambda _path: False
) -> bytes:
    """A tar of ``files`` (and their parent folders) owned by the sandbox user,
    for ``put_archive`` into ``/workspace``. Files only carry text, so
    ``executable`` says which ones get the executable bit (a pack's
    ``executables``, e.g. Rails' ``bin/*``)."""
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
            info.mode = 0o755 if executable(path) else 0o644
            info.uid = info.gid = SANDBOX_UID
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class _ChunkReader(io.RawIOBase):
    """A file over an iterator of byte chunks, for streaming ``tarfile``."""

    def __init__(self, chunks: Iterable[bytes], limit: int) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""
        self._left = limit

    def readable(self) -> bool:
        return True

    def readinto(self, target: Any) -> int:
        while not self._buffer:
            chunk = next(self._chunks, b"")
            if not chunk:
                return 0
            self._left -= len(chunk)
            if self._left < 0:
                raise ValueError("The workspace is too large to save")
            self._buffer = chunk
        size = min(len(target), len(self._buffer))
        target[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


def read_snapshot(
    chunks: Iterable[bytes], root: str = "workspace", extra: frozenset[str] = frozenset()
) -> tuple[dict[str, str], list[str]]:
    """Text files from a ``get_archive`` stream of ``/workspace``, read as it
    arrives so ignored folders (a dev server's build cache can be hundreds of
    MB) are skipped rather than held in memory.

    Returns ``(files, skipped)``: ``skipped`` lists paths left out because they
    are binary, too large, or past the size budget. Symlinks and other
    non-regular entries are ignored.
    """
    files: dict[str, str] = {}
    skipped: list[str] = []
    kept = 0
    reader = io.BufferedReader(_ChunkReader(chunks, MAX_ARCHIVE_BYTES), 1024 * 1024)
    try:
        with tarfile.open(fileobj=reader, mode="r|") as tar:
            for member in tar:
                name = member.name
                if name == root or not name.startswith(root + "/") or not member.isreg():
                    continue
                path = name[len(root) + 1 :]
                if is_ignored(path, extra):
                    continue
                too_much = len(files) >= MAX_FILES or kept + member.size > MAX_SNAPSHOT_BYTES
                extracted = None if too_much else tar.extractfile(member)
                if member.size > MAX_FILE_BYTES or extracted is None:
                    skipped.append(path)
                    continue
                data = extracted.read()
                try:
                    files[path] = data.decode()
                except UnicodeDecodeError:
                    skipped.append(path)
                    continue
                kept += len(data)
    except tarfile.TarError as exc:
        raise ValueError(f"Could not read the workspace ({exc})") from exc
    return dict(sorted(files.items())), sorted(skipped)
