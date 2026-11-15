"""The dependencies a pack allows, and checking a project against them.

Sandboxes have no network, so a project can only use what the pack image
installed. ``pack.toml``'s ``[dependencies]`` table says what that is::

    [dependencies]
    manager = "npm"            # "npm" (package.json) or "bundler" (Gemfile)
    allowed = { next = "16.4.6", react = "19.3.1" }

When a pack loads, the manifest is checked against the pack's own lockfile
both ways: every allowed package is installed at exactly that version, and
every package the pack installs directly is allowed. So the manifest can be
trusted as the complete list, and a project generator can be held to it with
:func:`project_problems` (the runner also refuses to create a sandbox whose
files break it).

Project rules, kept simple enough to state in a prompt:

- npm: every ``package.json`` may only name allowed packages, each as ``*``,
  the exact version, ``^version`` or ``~version``.
- bundler: the ``Gemfile`` may only name allowed gems (from rubygems, no
  ``git:``/``path:``/``gemspec``), with version requirements the installed
  version meets. A ``Gemfile.lock`` must only lock installed versions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANAGERS = ("npm", "bundler")
_NPM_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
_VERSION = re.compile(r"^\d+(\.\d+)*([.-][0-9A-Za-z.-]+)?$")
_GEM_LINE = re.compile(r"""^\s*gem\s*\(?\s*["']([^"']+)["'](.*)$""")
_GEM_REQUIREMENT = re.compile(r"""["']\s*(~>|>=|<=|!=|=|>|<)?\s*([0-9][0-9A-Za-z.]*)\s*["']""")
_LOCK_SPEC = re.compile(r"^    ([^\s(]+) \(([^)]+)\)$")
_LOCK_DEPENDENCY = re.compile(r"^  ([^\s(!]+)")
MAX_PROBLEMS = 50


@dataclass(frozen=True, slots=True)
class DependencyManifest:
    manager: str
    # Package -> the exact version installed, for the packages a project may name.
    allowed: dict[str, str]
    # Everything installed (transitive dependencies too) -> version, so a
    # project's lockfile can be checked as well.
    installed: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"manager": self.manager, "allowed": dict(sorted(self.allowed.items()))}


# -- loading (pack side) -------------------------------------------------------


def _npm_installed(pack_dir: Path) -> tuple[dict[str, str], set[str]]:
    """``(every installed package -> version, the pack's direct dependencies)``."""
    try:
        lock = json.loads((pack_dir / "package-lock.json").read_text())
        manifest = json.loads((pack_dir / "package.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"npm packs need package.json and package-lock.json ({exc})") from exc
    installed: dict[str, str] = {}
    for path, entry in lock.get("packages", {}).items():
        # Only the top-level copy is what `require(name)` finds.
        if path.startswith("node_modules/") and path.count("node_modules/") == 1:
            installed[path.removeprefix("node_modules/")] = str(entry.get("version", ""))
    direct = {name for section in _NPM_SECTIONS for name in manifest.get(section, {})}
    return installed, direct


def parse_gemfile_lock(text: str) -> tuple[dict[str, str], set[str]]:
    """``(every locked gem -> version, the Gemfile's own gems)``. Platform
    suffixes (``2.10.2-x86_64-linux-gnu``) are dropped."""
    installed: dict[str, str] = {}
    direct: set[str] = set()
    section = ""
    for line in text.splitlines():
        if line and not line.startswith(" "):
            section = line.strip()
            continue
        if section == "GEM" and (spec := _LOCK_SPEC.match(line)):
            version = spec.group(2).split("-")[0]
            installed.setdefault(spec.group(1), version)
        elif section == "DEPENDENCIES" and (dependency := _LOCK_DEPENDENCY.match(line)):
            direct.add(dependency.group(1))
    return installed, direct


def _bundler_installed(pack_dir: Path) -> tuple[dict[str, str], set[str]]:
    try:
        return parse_gemfile_lock((pack_dir / "Gemfile.lock").read_text())
    except OSError as exc:
        raise ValueError(f"bundler packs need a Gemfile.lock ({exc})") from exc


def load_manifest(raw: Any, pack_dir: Path) -> DependencyManifest:
    """Validate a ``[dependencies]`` table against what the pack installs."""
    if not isinstance(raw, dict):
        raise ValueError("[dependencies] must be a table")
    manager = raw.get("manager")
    if manager not in MANAGERS:
        raise ValueError(f"[dependencies] manager must be one of {', '.join(MANAGERS)}")
    allowed = raw.get("allowed")
    if not isinstance(allowed, dict) or not allowed:
        raise ValueError("[dependencies] allowed must map each package to its version")
    for name, version in allowed.items():
        if not isinstance(version, str) or not _VERSION.match(version):
            raise ValueError(f"[dependencies] {name} needs an exact version, not {version!r}")

    installed, direct = (_npm_installed if manager == "npm" else _bundler_installed)(pack_dir)
    wrong = [
        f"{name} {version} (installed: {installed.get(name, 'none')})"
        for name, version in sorted(allowed.items())
        if installed.get(name) != version
    ]
    if wrong:
        raise ValueError(f"allowed versions differ from the pack's lockfile: {', '.join(wrong)}")
    if missing := sorted(direct - set(allowed)):
        raise ValueError(f"the pack installs {', '.join(missing)} but does not allow it")
    return DependencyManifest(manager=manager, allowed=dict(allowed), installed=installed)


# -- checking a project ----------------------------------------------------------


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """Comparable segments: numbers compare as numbers and sort after
    pre-release words (``1.0.rc1`` < ``1.0.0``), like ``Gem::Version``."""
    parts = re.findall(r"\d+|[A-Za-z]+", version)
    return tuple((1, int(p)) if p.isdigit() else (0, p) for p in parts)


def _gem_requirement_met(op: str, wanted: str, version: str) -> bool:
    have, want = _version_key(version), _version_key(wanted)
    if op == "~>":
        # "~> 2.1" is >= 2.1 and < 3; "~> 2.1.3" is >= 2.1.3 and < 2.2.
        numbers = wanted.split(".")
        prefix = numbers[:-1] if len(numbers) > 1 else numbers
        bump = [*prefix[:-1], str(int(prefix[-1]) + 1)] if prefix[-1].isdigit() else prefix
        return have >= want and have < _version_key(".".join(bump))
    return {
        "=": have == want,
        "!=": have != want,
        ">": have > want,
        "<": have < want,
        ">=": have >= want,
        "<=": have <= want,
    }[op]


def _npm_problems(manifest: DependencyManifest, path: str, text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return [f"{path} is not valid JSON"]
    if not isinstance(data, dict):
        return [f"{path} must be a JSON object"]
    problems: list[str] = []
    for section in _NPM_SECTIONS:
        entries = data.get(section) or {}
        if not isinstance(entries, dict):
            problems.append(f"{path}: {section} must be an object")
            continue
        for name, spec in entries.items():
            version = manifest.allowed.get(name)
            if version is None:
                problems.append(f"{path}: {name} is not installed in this sandbox")
            elif spec not in ("*", version, f"^{version}", f"~{version}"):
                problems.append(f"{path}: {name} must be {version!r} (the installed version)")
    return problems


def _npm_lock_problems(manifest: DependencyManifest, path: str, text: str) -> list[str]:
    try:
        packages = json.loads(text).get("packages", {})
    except (ValueError, AttributeError):
        return [f"{path} is not a valid package-lock.json"]
    problems = []
    for key, entry in packages.items():
        # Only top-level copies: nested ones are only reachable through them.
        if not key.startswith("node_modules/") or key.count("node_modules/") != 1:
            continue
        name = key.removeprefix("node_modules/")
        if not isinstance(entry, dict) or entry.get("link"):
            continue
        version = entry.get("version")
        if version and manifest.installed.get(name) != version:
            problems.append(f"{path}: {name} {version} is not installed in this sandbox")
    return problems


def _gemfile_problems(manifest: DependencyManifest, path: str, text: str) -> list[str]:
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        code = line.split("#", 1)[0]
        stripped = code.strip()
        if stripped.startswith(("gemspec", "git_source", "path ", "path(", "git ", "github ")):
            problems.append(f"{path}:{number}: only gems from the pack are available")
            continue
        gem = _GEM_LINE.match(code)
        if gem is None:
            continue
        name, rest = gem.group(1), gem.group(2)
        version = manifest.allowed.get(name)
        if version is None:
            problems.append(f"{path}:{number}: {name} is not installed in this sandbox")
            continue
        if re.search(r"\b(git|github|path|source)\s*:", rest):
            problems.append(f"{path}:{number}: {name} must come from the installed gems")
            continue
        # Requirements come before the first keyword option (require:, group: ...).
        requirements = re.split(r"\b\w+\s*:", rest, maxsplit=1)[0]
        for op, wanted in _GEM_REQUIREMENT.findall(requirements):
            if not _gem_requirement_met(op or "=", wanted, version):
                problems.append(f"{path}:{number}: {name} {op or '='} {wanted} excludes {version}")
    return problems


def _gemfile_lock_problems(manifest: DependencyManifest, path: str, text: str) -> list[str]:
    locked, _ = parse_gemfile_lock(text)
    return [
        f"{path}: {name} {version} is not installed in this sandbox"
        for name, version in sorted(locked.items())
        if manifest.installed.get(name) != version
    ]


def project_problems(manifest: DependencyManifest, files: dict[str, str]) -> list[str]:
    """Why a project's dependency files break the manifest (empty = fine)."""
    problems: list[str] = []
    for path, text in sorted(files.items()):
        name = path.rpartition("/")[2]
        if manifest.manager == "npm" and name == "package.json":
            problems += _npm_problems(manifest, path, text)
        elif manifest.manager == "npm" and name == "package-lock.json":
            problems += _npm_lock_problems(manifest, path, text)
        elif manifest.manager == "bundler" and name == "Gemfile":
            problems += _gemfile_problems(manifest, path, text)
        elif manifest.manager == "bundler" and name == "Gemfile.lock":
            problems += _gemfile_lock_problems(manifest, path, text)
    return problems[:MAX_PROBLEMS]
