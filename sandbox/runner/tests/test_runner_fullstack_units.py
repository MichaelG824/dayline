"""Full-stack pack pieces that need no Docker: the manifest's new sections,
dependency checks, dev-server logs, the preview cookie jar and paths."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from dayline_runner.cookies import CookieJar
from dayline_runner.deps import DependencyManifest, parse_gemfile_lock, project_problems
from dayline_runner.packs import PackError, load_pack, load_packs
from dayline_runner.preview import raw_suffix
from dayline_runner.servers import LogBuffer
from dayline_runner.workspace import (
    WorkspacePathError,
    clean_path,
    file_tar,
    read_snapshot,
)

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


def test_full_stack_packs_declare_servers_and_complete_dependency_lists() -> None:
    packs = load_packs(PACKS_DIR)
    nest, rails = packs["next-nest"], packs["rails"]
    assert [(s.name, s.port) for s in nest.servers] == [("api", 4000), ("web", 3000)]
    assert [(s.name, s.port) for s in rails.servers] == [("web", 3000)]
    assert nest.dependencies and nest.dependencies.manager == "npm"
    assert nest.dependencies.allowed["next"] == "16.4.6"
    assert rails.dependencies and rails.dependencies.manager == "bundler"
    assert rails.dependencies.allowed["rails"] == "8.1.4.1"
    # Transitive gems are known too, so a project's Gemfile.lock can be checked.
    assert "activerecord" in rails.dependencies.installed
    assert rails.is_executable("bin/rails") and not rails.is_executable("app/models/note.rb")
    assert ".next" in nest.ignore and "tmp" in rails.ignore
    assert nest.memory == "1536m" and rails.memory is None
    for pack in (nest, rails):
        assert pack.hidden_test_cmd and "{" not in pack.hidden_test_cmd


def _pack(tmp_path: Path, extra: str, files: dict[str, str] | None = None) -> Path:
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "Dockerfile").write_text("FROM scratch\n")
    (folder / "pack.toml").write_text(f'name = "demo"\ntest_cmd = "t {{junit}}"\n{extra}')
    for name, text in (files or {}).items():
        (folder / name).write_text(text)
    return folder


NPM_FILES = {
    "package.json": json.dumps({"dependencies": {"left-pad": "1.3.0"}}),
    "package-lock.json": json.dumps({"packages": {"node_modules/left-pad": {"version": "1.3.0"}}}),
}


@pytest.mark.parametrize(
    ("extra", "files"),
    [
        ('[[servers]]\nname = "web"\ncommand = "x"\nport = 80\n', None),  # Privileged port.
        ('[[servers]]\nname = "Web"\ncommand = "x"\nport = 3000\n', None),
        ('[[servers]]\nname = "web"\ncommand = ""\nport = 3000\n', None),
        ('[[servers]]\nname = "web"\ncommand = "x"\nport = 3000\nready_path = "up"\n', None),
        (
            '[[servers]]\nname = "a"\ncommand = "x"\nport = 3000\n'
            '[[servers]]\nname = "b"\ncommand = "y"\nport = 3000\n',
            None,
        ),  # Same port twice.
        ('ignore = ["a/b"]\n', None),
        ('memory = "lots"\n', None),
        ('executables = "bin/*"\n', None),
        ('[dependencies]\nmanager = "pip"\nallowed = { x = "1" }\n', None),
        ('[dependencies]\nmanager = "npm"\nallowed = { left-pad = "^1.3.0" }\n', NPM_FILES),
        ('[dependencies]\nmanager = "npm"\nallowed = { left-pad = "1.2.0" }\n', NPM_FILES),
        ('[dependencies]\nmanager = "npm"\nallowed = { other = "1.0.0" }\n', NPM_FILES),
    ],
)
def test_invalid_full_stack_sections_are_rejected(
    tmp_path: Path, extra: str, files: dict[str, str] | None
) -> None:
    with pytest.raises(PackError):
        load_pack(_pack(tmp_path, extra, files))


def test_the_manifest_must_cover_everything_the_pack_installs(tmp_path: Path) -> None:
    files = {
        **NPM_FILES,
        "package.json": json.dumps(
            {"dependencies": {"left-pad": "1.3.0"}, "devDependencies": {"extra": "1.0.0"}}
        ),
    }
    with pytest.raises(PackError, match="installs extra but does not allow it"):
        load_pack(_pack(tmp_path, '[dependencies]\nmanager = "npm"\n'
                        'allowed = { left-pad = "1.3.0" }\n', files))  # fmt: skip


NPM = DependencyManifest(
    manager="npm",
    allowed={"next": "16.4.6", "react": "19.3.1"},
    installed={"next": "16.4.6", "react": "19.3.1", "scheduler": "0.27.0"},
)


def test_npm_projects_may_only_use_installed_packages_at_installed_versions() -> None:
    ok = {
        "package.json": json.dumps({"dependencies": {"next": "16.4.6", "react": "^19.3.1"}}),
        "web/package.json": json.dumps({"devDependencies": {"react": "*"}}),
        "README.md": "anything",
    }
    assert project_problems(NPM, ok) == []
    bad = {
        "package.json": json.dumps({"dependencies": {"next": "^15.0.0", "lodash": "4.17.21"}}),
        "web/package.json": "{not json",
        "package-lock.json": json.dumps(
            {"packages": {"node_modules/react": {"version": "18.0.0"}}}
        ),
    }
    problems = project_problems(NPM, bad)
    assert any("next must be '16.4.6'" in p for p in problems)
    assert any("lodash is not installed" in p for p in problems)
    assert any("web/package.json is not valid JSON" in p for p in problems)
    assert any("react 18.0.0 is not installed" in p for p in problems)


GEMS = DependencyManifest(
    manager="bundler",
    allowed={"rails": "8.1.4.1", "puma": "8.1.1", "debug": "1.11.1"},
    installed={"rails": "8.1.4.1", "puma": "8.1.1", "debug": "1.11.1", "rack": "3.2.8"},
)


def test_gemfiles_may_only_name_installed_gems_with_requirements_they_meet() -> None:
    ok = (
        'source "https://rubygems.org"\n'
        'gem "rails", "~> 8.1.0"\n'
        "gem 'puma', '>= 8.0', '< 9'\n"
        'gem "debug", require: "debug/prelude", groups: %i[development test]  # a note\n'
        '# gem "commented-out"\n'
    )
    assert project_problems(GEMS, {"Gemfile": ok}) == []
    bad = (
        'gem "rails", "~> 8.0.0"\n'
        'gem "devise"\n'
        'gem "puma", git: "https://example.com/puma.git"\n'
        "gemspec\n"
    )
    problems = project_problems(GEMS, {"Gemfile": bad})
    assert problems == [
        "Gemfile:1: rails ~> 8.0.0 excludes 8.1.4.1",
        "Gemfile:2: devise is not installed in this sandbox",
        "Gemfile:3: puma must come from the installed gems",
        "Gemfile:4: only gems from the pack are available",
    ]


def test_gemfile_locks_must_lock_installed_versions() -> None:
    lock = (
        "GEM\n  remote: https://rubygems.org/\n  specs:\n"
        "    rack (3.2.8)\n    rails (8.1.4.1)\n    puma (7.0.0-x86_64-linux-gnu)\n\n"
        "PLATFORMS\n  x86_64-linux-gnu\n\nDEPENDENCIES\n  puma\n  rails (= 8.1.4.1)\n"
    )
    locked, direct = parse_gemfile_lock(lock)
    assert locked["puma"] == "7.0.0" and direct == {"puma", "rails"}
    assert project_problems(GEMS, {"Gemfile.lock": lock}) == [
        "Gemfile.lock: puma 7.0.0 is not installed in this sandbox"
    ]


def test_server_logs_keep_a_clean_bounded_tail() -> None:
    log = LogBuffer(max_lines=3)
    log.write(b"\x1bc\x1b(B\x1b[32mready\x1b[0m in 5ms\r\nhalf")
    log.write(b" a line\n10%\r50%\r100%\n\xe2\x9c")
    log.write(b"\x93 done\n")
    assert log.read(0) == {
        "lines": ["half a line", "100%", "✓ done"],
        "next": 4,
        "truncated": True,  # "ready in 5ms" was dropped.
    }
    fresh = LogBuffer()
    fresh.write(b"\x1bc\x1b(B\x1b]0;title\x07Restarting 'src/main.ts'\n")
    assert fresh.read(0)["lines"] == ["Restarting 'src/main.ts'"]
    log.note("Stopped web")
    assert log.read(4) == {"lines": ["[dayline] Stopped web"], "next": 5, "truncated": False}
    assert log.read(5)["lines"] == []


def test_the_cookie_jar_scopes_expires_and_replaces_cookies() -> None:
    now = [1_000.0]
    jar = CookieJar(clock=lambda: now[0])
    base = "/api/preview/s1/tok/3000"
    jar.store("_app_session=abc; path=/; HttpOnly; SameSite=Lax", f"{base}/notes")
    jar.store("scoped=1; Path=/api/preview/s1/tok/3000/admin", f"{base}/admin")
    jar.store("short=1; Max-Age=60; Expires=Wed, 01 Jan 2099 00:00:00 GMT", base)
    jar.store("gone=1; Expires=Thu, 01 Jan 1970 00:00:00 GMT", base)
    assert jar.header(f"{base}/admin/users?x=1") == "scoped=1; short=1; _app_session=abc"
    assert jar.header(f"{base}/notes") == "short=1; _app_session=abc"
    now[0] += 61  # Max-Age wins over the far-off Expires.
    jar.store("_app_session=def; Path=/", base)
    assert jar.header(f"{base}/notes") == "_app_session=def"
    jar.store("_app_session=; Path=/; Max-Age=0", base)
    assert jar.header(f"{base}/notes") is None


@pytest.mark.parametrize(
    ("raw", "suffix"),
    [
        (b"/sandboxes/s1/preview/3000", ""),
        (b"/sandboxes/s1/preview/3000/", "/"),
        (b"/sandboxes/s1/preview/3000/_next/a%2Fb%20c.js", "/_next/a%2Fb%20c.js"),
    ],
)
def test_preview_paths_stay_raw(raw: bytes, suffix: str) -> None:
    assert raw_suffix({"raw_path": raw, "path": raw.decode()}) == suffix


def test_pack_ignored_folders_stay_out_of_paths_and_snapshots() -> None:
    extra = frozenset({".next", "tmp"})
    with pytest.raises(WorkspacePathError):
        clean_path("web/.next/cache.json", extra)
    assert clean_path("web/.next/cache.json") == "web/.next/cache.json"

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for name, data in [
            ("workspace/web/page.tsx", b"export {}\n"),
            ("workspace/web/.next/cache/big.pack", b"\0" * (3 * 1024 * 1024)),
            ("workspace/tmp/pids/server.pid", b"12\n"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    raw = archive.getvalue()
    chunks = [raw[i : i + 4096] for i in range(0, len(raw), 4096)]
    files, skipped = read_snapshot(chunks, extra=extra)
    assert files == {"web/page.tsx": "export {}\n"} and skipped == []


def test_executables_keep_their_mode() -> None:
    tar_bytes = file_tar(
        {"bin/rails": b"#!/usr/bin/env ruby\n", "Gemfile": b""}, lambda p: p.startswith("bin/")
    )
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        modes = {m.name: m.mode for m in tar.getmembers() if m.isfile()}
    assert modes == {"bin/rails": 0o755, "Gemfile": 0o644}
