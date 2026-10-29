"""LeetCode problem source interface + in-memory fake + Supabase implementation.

``ProblemSource`` covers the three tables behind the Problems tab: problems
(with their tag links), their solutions, and the shared tag list. Kept
stdlib-only, mirroring the ``TaskSource``/``InterviewSource`` pattern: only the
concrete Supabase implementation imports a third-party client.

Problems never feed ``build_plan`` - a scheduled practice session is an
ordinary :class:`~dayline.models.Task` linked via ``Task.problem_id``.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from dayline.models import Difficulty, Problem, ProblemStatus, ProblemTag, Solution


@runtime_checkable
class ProblemSource(Protocol):
    """Read/write surface over problems, their solutions, and tags."""

    def list_problems(self) -> list[Problem]:
        """Return every problem, starred first then newest first."""
        ...

    def get_problem(self, problem_id: str) -> Problem:
        """Return a single problem by id. Raises ``KeyError`` if absent."""
        ...

    def create_problem(self, problem: Problem) -> Problem:
        """Persist a new problem (and its tag links); return it as stored."""
        ...

    def update_problem(self, problem: Problem) -> Problem:
        """Replace every editable field of an existing problem, including its
        tag links, with ``problem``'s values. Raises ``KeyError`` if absent."""
        ...

    def delete_problem(self, problem_id: str) -> None:
        """Delete a problem and its solutions. No-op if it is already gone."""
        ...

    def list_solutions(self, problem_id: str) -> list[Solution]:
        """Return a problem's solutions, optimal first then oldest first."""
        ...

    def get_solution(self, solution_id: str) -> Solution:
        """Return a single solution by id. Raises ``KeyError`` if absent."""
        ...

    def create_solution(self, solution: Solution) -> Solution:
        """Persist a new solution; return it as stored."""
        ...

    def update_solution(self, solution: Solution) -> Solution:
        """Replace every editable field of an existing solution. Raises
        ``KeyError`` if absent."""
        ...

    def delete_solution(self, solution_id: str) -> None:
        """Delete a solution by id. No-op if it is already gone."""
        ...

    def list_tags(self) -> list[ProblemTag]:
        """Return every tag, alphabetical."""
        ...

    def create_tag(self, tag: ProblemTag) -> ProblemTag:
        """Persist a new tag; return it as stored."""
        ...

    def update_tag(self, tag: ProblemTag) -> ProblemTag:
        """Rename/recolor a tag. Raises ``KeyError`` if absent."""
        ...

    def delete_tag(self, tag_id: str) -> None:
        """Delete a tag, detaching it from every problem. No-op if gone."""
        ...


def _problem_sort_key(p: Problem) -> tuple[bool, float]:
    created = p.created_at.timestamp() if p.created_at else 0.0
    return (not p.starred, -created)


def _solution_sort_key(s: Solution) -> tuple[bool, float]:
    created = s.created_at.timestamp() if s.created_at else 0.0
    return (not s.is_optimal, created)


class InMemoryProblemSource:
    """A fully working in-memory :class:`ProblemSource` for tests - no
    network, no credentials. Copies are returned on read so callers can't
    mutate internal state by accident."""

    def __init__(
        self,
        problems: list[Problem] | None = None,
        tags: list[ProblemTag] | None = None,
        solutions: list[Solution] | None = None,
    ) -> None:
        self._problems = {p.id: copy.deepcopy(p) for p in problems or []}
        self._tags = {t.id: copy.deepcopy(t) for t in tags or []}
        self._solutions = {s.id: copy.deepcopy(s) for s in solutions or []}

    def list_problems(self) -> list[Problem]:
        # Reversed insertion order first, so the stable sort breaks equal
        # created_at timestamps newest-first too.
        result = sorted(reversed(self._problems.values()), key=_problem_sort_key)
        return [copy.deepcopy(p) for p in result]

    def get_problem(self, problem_id: str) -> Problem:
        return copy.deepcopy(self._problems[problem_id])

    def create_problem(self, problem: Problem) -> Problem:
        stored = copy.deepcopy(problem)
        now = datetime.now(UTC)
        stored.created_at = stored.created_at or now
        stored.updated_at = now
        self._problems[stored.id] = stored
        return copy.deepcopy(stored)

    def update_problem(self, problem: Problem) -> Problem:
        existing = self._problems[problem.id]
        stored = copy.deepcopy(problem)
        stored.created_at = existing.created_at
        stored.updated_at = datetime.now(UTC)
        self._problems[stored.id] = stored
        return copy.deepcopy(stored)

    def delete_problem(self, problem_id: str) -> None:
        self._problems.pop(problem_id, None)
        for sid in [s.id for s in self._solutions.values() if s.problem_id == problem_id]:
            del self._solutions[sid]

    def list_solutions(self, problem_id: str) -> list[Solution]:
        result = sorted(
            (s for s in self._solutions.values() if s.problem_id == problem_id),
            key=_solution_sort_key,
        )
        return [copy.deepcopy(s) for s in result]

    def get_solution(self, solution_id: str) -> Solution:
        return copy.deepcopy(self._solutions[solution_id])

    def create_solution(self, solution: Solution) -> Solution:
        stored = copy.deepcopy(solution)
        stored.created_at = stored.created_at or datetime.now(UTC)
        self._solutions[stored.id] = stored
        return copy.deepcopy(stored)

    def update_solution(self, solution: Solution) -> Solution:
        existing = self._solutions[solution.id]
        stored = copy.deepcopy(solution)
        stored.created_at = existing.created_at
        self._solutions[stored.id] = stored
        return copy.deepcopy(stored)

    def delete_solution(self, solution_id: str) -> None:
        self._solutions.pop(solution_id, None)

    def list_tags(self) -> list[ProblemTag]:
        result = sorted(self._tags.values(), key=lambda t: t.name.lower())
        return [copy.deepcopy(t) for t in result]

    def create_tag(self, tag: ProblemTag) -> ProblemTag:
        self._tags[tag.id] = copy.deepcopy(tag)
        return copy.deepcopy(tag)

    def update_tag(self, tag: ProblemTag) -> ProblemTag:
        if tag.id not in self._tags:
            raise KeyError(tag.id)
        self._tags[tag.id] = copy.deepcopy(tag)
        return copy.deepcopy(tag)

    def delete_tag(self, tag_id: str) -> None:
        self._tags.pop(tag_id, None)
        for problem in self._problems.values():
            if tag_id in problem.tag_ids:
                problem.tag_ids.remove(tag_id)


# --------------------------------------------------------------------------- #
# Supabase-backed ProblemSource
# --------------------------------------------------------------------------- #

# Embeds each problem's tag links in the same request (PostgREST follows the
# problem_tag_links.problem_id foreign key).
_PROBLEM_SELECT = "*, problem_tag_links(tag_id)"


def _parse_dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _problem_to_row(problem: Problem) -> dict[str, Any]:
    """Every editable column. ``created_at``/``updated_at`` are left to the
    database defaults and trigger unless explicitly set (an import)."""
    row: dict[str, Any] = {
        "id": problem.id,
        "number": problem.number,
        "slug": problem.slug,
        "title": problem.title,
        "url": problem.url,
        "difficulty": problem.difficulty.value,
        "status": problem.status.value,
        "confidence": problem.confidence,
        "notes": problem.notes,
        "starred": problem.starred,
        "last_attempted_at": _iso(problem.last_attempted_at),
        "solved_at": _iso(problem.solved_at),
    }
    if problem.created_at is not None:
        row["created_at"] = problem.created_at.isoformat()
    return row


def _row_to_problem(row: dict[str, Any]) -> Problem:
    return Problem(
        id=row["id"],
        number=row.get("number"),
        slug=row.get("slug"),
        title=row["title"],
        url=row.get("url"),
        difficulty=Difficulty(row["difficulty"]),
        status=ProblemStatus(row["status"]),
        confidence=row.get("confidence"),
        notes=row.get("notes") or "",
        starred=bool(row.get("starred", False)),
        tag_ids=sorted(link["tag_id"] for link in row.get("problem_tag_links") or []),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
        last_attempted_at=_parse_dt(row.get("last_attempted_at")),
        solved_at=_parse_dt(row.get("solved_at")),
    )


def _solution_to_row(solution: Solution) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": solution.id,
        "problem_id": solution.problem_id,
        "title": solution.title,
        "language": solution.language,
        "code": solution.code,
        "time_complexity": solution.time_complexity,
        "space_complexity": solution.space_complexity,
        "explanation": solution.explanation,
        "is_optimal": solution.is_optimal,
    }
    if solution.created_at is not None:
        row["created_at"] = solution.created_at.isoformat()
    return row


def _row_to_solution(row: dict[str, Any]) -> Solution:
    return Solution(
        id=row["id"],
        problem_id=row["problem_id"],
        title=row["title"],
        language=row["language"],
        code=row.get("code") or "",
        time_complexity=row.get("time_complexity"),
        space_complexity=row.get("space_complexity"),
        explanation=row.get("explanation") or "",
        is_optimal=bool(row.get("is_optimal", False)),
        created_at=_parse_dt(row.get("created_at")),
    )


def _row_to_tag(row: dict[str, Any]) -> ProblemTag:
    return ProblemTag(id=row["id"], name=row["name"], color=row.get("color"))


class SupabaseProblemSource:
    """Real Supabase-backed :class:`ProblemSource`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def list_problems(self) -> list[Problem]:
        resp = (
            self._client.table("problems")
            .select(_PROBLEM_SELECT)
            .order("starred", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
        return [_row_to_problem(row) for row in resp.data]

    def get_problem(self, problem_id: str) -> Problem:
        resp = self._client.table("problems").select(_PROBLEM_SELECT).eq("id", problem_id).execute()
        if not resp.data:
            raise KeyError(problem_id)
        return _row_to_problem(resp.data[0])

    def _set_tag_links(self, problem_id: str, tag_ids: list[str]) -> None:
        links = self._client.table("problem_tag_links")
        links.delete().eq("problem_id", problem_id).execute()
        if tag_ids:
            links.insert(
                [{"problem_id": problem_id, "tag_id": tag_id} for tag_id in tag_ids]
            ).execute()

    def create_problem(self, problem: Problem) -> Problem:
        self._client.table("problems").insert(_problem_to_row(problem)).execute()
        self._set_tag_links(problem.id, problem.tag_ids)
        return self.get_problem(problem.id)

    def update_problem(self, problem: Problem) -> Problem:
        row = _problem_to_row(problem)
        row.pop("created_at", None)
        resp = self._client.table("problems").update(row).eq("id", problem.id).execute()
        if not resp.data:
            raise KeyError(problem.id)
        self._set_tag_links(problem.id, problem.tag_ids)
        return self.get_problem(problem.id)

    def delete_problem(self, problem_id: str) -> None:
        # Solutions and tag links cascade (see migration 010).
        self._client.table("problems").delete().eq("id", problem_id).execute()

    def list_solutions(self, problem_id: str) -> list[Solution]:
        resp = (
            self._client.table("problem_solutions")
            .select("*")
            .eq("problem_id", problem_id)
            .order("is_optimal", desc=True)
            .order("created_at")
            .execute()
        )
        return [_row_to_solution(row) for row in resp.data]

    def get_solution(self, solution_id: str) -> Solution:
        resp = self._client.table("problem_solutions").select("*").eq("id", solution_id).execute()
        if not resp.data:
            raise KeyError(solution_id)
        return _row_to_solution(resp.data[0])

    def create_solution(self, solution: Solution) -> Solution:
        resp = self._client.table("problem_solutions").insert(_solution_to_row(solution)).execute()
        return _row_to_solution(resp.data[0])

    def update_solution(self, solution: Solution) -> Solution:
        row = _solution_to_row(solution)
        row.pop("created_at", None)
        row.pop("problem_id")
        resp = self._client.table("problem_solutions").update(row).eq("id", solution.id).execute()
        if not resp.data:
            raise KeyError(solution.id)
        return _row_to_solution(resp.data[0])

    def delete_solution(self, solution_id: str) -> None:
        self._client.table("problem_solutions").delete().eq("id", solution_id).execute()

    def list_tags(self) -> list[ProblemTag]:
        resp = self._client.table("problem_tags").select("*").order("name").execute()
        return [_row_to_tag(row) for row in resp.data]

    def create_tag(self, tag: ProblemTag) -> ProblemTag:
        resp = (
            self._client.table("problem_tags")
            .insert({"id": tag.id, "name": tag.name, "color": tag.color})
            .execute()
        )
        return _row_to_tag(resp.data[0])

    def update_tag(self, tag: ProblemTag) -> ProblemTag:
        resp = (
            self._client.table("problem_tags")
            .update({"name": tag.name, "color": tag.color})
            .eq("id", tag.id)
            .execute()
        )
        if not resp.data:
            raise KeyError(tag.id)
        return _row_to_tag(resp.data[0])

    def delete_tag(self, tag_id: str) -> None:
        # Tag links cascade (see migration 010).
        self._client.table("problem_tags").delete().eq("id", tag_id).execute()
