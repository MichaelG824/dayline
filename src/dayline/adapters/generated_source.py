"""Generated practice projects: interface + in-memory fake + Supabase.

A :class:`~dayline.models.GeneratedProject` is one generation from the Mock
tab's project generator (``mock/project_gen.py``): the candidate's inputs and
imported context files, live progress while it runs, and the validated
project once it is ready. Rows are private to their ``owner`` (the signed-in
email); every read here takes the owner, so one user never sees another's.
Kept stdlib-only like the other sources: only the Supabase implementation
talks to a third-party client.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from dayline.models import GeneratedProject, GenerationStatus


@runtime_checkable
class GeneratedProjectSource(Protocol):
    """``get`` and ``update`` raise ``KeyError`` if the project is absent (or
    not the owner's); ``delete`` is a no-op if it is already gone."""

    def list_projects(self, owner: str) -> list[GeneratedProject]:
        """The owner's projects, newest first."""
        ...

    def get(self, owner: str, project_id: str) -> GeneratedProject: ...

    def get_any(self, project_id: str) -> GeneratedProject:
        """A project by id whatever its owner: a staged round names its
        problem by id alone, and the session already proved ownership."""
        ...

    def create(self, project: GeneratedProject) -> GeneratedProject: ...

    def update(self, project: GeneratedProject) -> GeneratedProject: ...

    def delete(self, owner: str, project_id: str) -> None: ...


def _created_key(project: GeneratedProject) -> float:
    return project.created_at.timestamp() if project.created_at else 0.0


class InMemoryGeneratedProjectSource:
    """A working in-memory source for tests. Copies on the way in and out."""

    def __init__(self, projects: list[GeneratedProject] | None = None) -> None:
        self._projects = {p.id: copy.deepcopy(p) for p in projects or []}

    def list_projects(self, owner: str) -> list[GeneratedProject]:
        mine = [p for p in reversed(self._projects.values()) if p.owner == owner]
        return [copy.deepcopy(p) for p in sorted(mine, key=_created_key, reverse=True)]

    def get(self, owner: str, project_id: str) -> GeneratedProject:
        project = self._projects.get(project_id)
        if project is None or project.owner != owner:
            raise KeyError(project_id)
        return copy.deepcopy(project)

    def get_any(self, project_id: str) -> GeneratedProject:
        return copy.deepcopy(self._projects[project_id])

    def create(self, project: GeneratedProject) -> GeneratedProject:
        stored = copy.deepcopy(project)
        now = datetime.now(UTC)
        stored.created_at = stored.created_at or now
        stored.updated_at = now
        self._projects[stored.id] = stored
        return copy.deepcopy(stored)

    def update(self, project: GeneratedProject) -> GeneratedProject:
        existing = self._projects.get(project.id)
        if existing is None or existing.owner != project.owner:
            raise KeyError(project.id)
        stored = copy.deepcopy(project)
        stored.created_at = existing.created_at
        stored.updated_at = datetime.now(UTC)
        self._projects[stored.id] = stored
        return copy.deepcopy(stored)

    def delete(self, owner: str, project_id: str) -> None:
        project = self._projects.get(project_id)
        if project is not None and project.owner == owner:
            del self._projects[project_id]


# --------------------------------------------------------------------------- #
# Supabase
# --------------------------------------------------------------------------- #

TABLE = "mock_generated_projects"


def _parse_dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _to_row(project: GeneratedProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "owner": project.owner,
        "status": project.status.value,
        "request": project.request,
        "context_files": project.context_files,
        "title": project.title,
        "progress": project.progress,
        "artifact": project.artifact,
        "error": project.error,
        "log": project.log,
        "usage": project.usage,
        "parent_id": project.parent_id,
        "finished_at": _iso(project.finished_at),
    }


def _from_row(row: dict[str, Any]) -> GeneratedProject:
    return GeneratedProject(
        id=row["id"],
        owner=row["owner"],
        status=GenerationStatus(row["status"]),
        request=dict(row.get("request") or {}),
        context_files=list(row.get("context_files") or []),
        title=row.get("title") or "",
        progress=dict(row.get("progress") or {}),
        artifact=row.get("artifact"),
        error=row.get("error") or "",
        log=list(row.get("log") or []),
        usage=dict(row.get("usage") or {}),
        parent_id=row.get("parent_id"),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
        finished_at=_parse_dt(row.get("finished_at")),
    )


class SupabaseGeneratedProjectSource:
    """Real Supabase-backed :class:`GeneratedProjectSource` (migration 015)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def list_projects(self, owner: str) -> list[GeneratedProject]:
        resp = (
            self._client.table(TABLE)
            .select("*")
            .eq("owner", owner)
            .order("created_at", desc=True)
            .execute()
        )
        return [_from_row(row) for row in resp.data]

    def get(self, owner: str, project_id: str) -> GeneratedProject:
        resp = (
            self._client.table(TABLE).select("*").eq("id", project_id).eq("owner", owner).execute()
        )
        if not resp.data:
            raise KeyError(project_id)
        return _from_row(resp.data[0])

    def get_any(self, project_id: str) -> GeneratedProject:
        resp = self._client.table(TABLE).select("*").eq("id", project_id).execute()
        if not resp.data:
            raise KeyError(project_id)
        return _from_row(resp.data[0])

    def create(self, project: GeneratedProject) -> GeneratedProject:
        resp = self._client.table(TABLE).insert(_to_row(project)).execute()
        return _from_row(resp.data[0])

    def update(self, project: GeneratedProject) -> GeneratedProject:
        row = _to_row(project)
        row.pop("id")  # updated_at is set by the table's trigger.
        resp = (
            self._client.table(TABLE)
            .update(row)
            .eq("id", project.id)
            .eq("owner", project.owner)
            .execute()
        )
        if not resp.data:
            raise KeyError(project.id)
        return _from_row(resp.data[0])

    def delete(self, owner: str, project_id: str) -> None:
        self._client.table(TABLE).delete().eq("id", project_id).eq("owner", owner).execute()
