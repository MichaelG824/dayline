"""Built-in practice repos for live mock sessions.

Each template is a folder under ``mock/templates/<id>/``: a ``template.toml``
plus a ``files/`` tree copied into the sandbox as the starting workspace.
``files/README.md`` is the task the candidate reads. The repos are hand-made
originals (never reported questions), so they are safe to demo.

Generated templates (from a reported question's spec) come later and will be
stored in Supabase alongside these.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from dayline.models import MockRoundType

TEMPLATES_DIR = Path(__file__).parent / "templates"
TASK_FILE = "README.md"


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    title: str
    pack: str
    round_type: MockRoundType
    duration_min: int
    summary: str
    # The file the editor opens first.
    open_path: str
    files: dict[str, str] = field(default_factory=dict)

    @property
    def task_md(self) -> str:
        return self.files.get(TASK_FILE, "")


def _load(folder: Path) -> Template:
    meta = tomllib.loads((folder / "template.toml").read_text())
    root = folder / "files"
    files = {
        p.relative_to(root).as_posix(): p.read_text()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    if TASK_FILE not in files:
        raise ValueError(f"Template {folder.name} has no files/{TASK_FILE}")
    open_path = str(meta.get("open") or TASK_FILE)
    if open_path not in files:
        raise ValueError(f"Template {folder.name} opens {open_path}, which is not in files/")
    return Template(
        id=folder.name,
        title=str(meta["title"]),
        pack=str(meta["pack"]),
        round_type=MockRoundType(meta["round_type"]),
        duration_min=int(meta["duration_min"]),
        summary=str(meta.get("summary", "")),
        open_path=open_path,
        files=files,
    )


@cache
def builtin_templates() -> dict[str, Template]:
    folders = sorted(d for d in TEMPLATES_DIR.iterdir() if (d / "template.toml").is_file())
    return {t.id: t for t in map(_load, folders)}
