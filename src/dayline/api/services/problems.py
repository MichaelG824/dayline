"""LeetCode problem orchestration over the problem source (the Problems tab).

Status-transition timestamps are stamped here, never by the client: moving into
``Solved`` stamps ``solved_at`` once, and moving into ``Attempted`` stamps
``last_attempted_at``. Problems never reach ``build_plan`` - a practice session
is an ordinary Leetcode task linked via ``Task.problem_id`` (see
``services/tasks.py``).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from dayline.api.context import AppContext
from dayline.api.parsing import parse_difficulty, parse_problem_status
from dayline.api.serializers import (
    problem_json,
    problem_tag_json,
    solution_json,
    task_json,
)
from dayline.models import Problem, ProblemStatus, ProblemTag, Solution

# Problem fields a client may set. Timestamps are server-owned.
EDITABLE_PROBLEM_FIELDS = frozenset(
    {
        "title",
        "difficulty",
        "status",
        "number",
        "slug",
        "url",
        "confidence",
        "notes",
        "starred",
        "tag_ids",
    }
)


def _get_problem(ctx: AppContext, problem_id: str) -> Problem:
    try:
        return ctx.problem_source.get_problem(problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No problem {problem_id!r}") from exc


def _get_solution(ctx: AppContext, solution_id: str) -> Solution:
    try:
        return ctx.problem_source.get_solution(solution_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No solution {solution_id!r}") from exc


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _apply_problem_changes(ctx: AppContext, problem: Problem, changes: dict[str, Any]) -> None:
    """Validate ``changes`` (snake_case, already restricted to
    :data:`EDITABLE_PROBLEM_FIELDS`) and write them onto ``problem``,
    stamping status-transition timestamps."""
    unknown = set(changes) - EDITABLE_PROBLEM_FIELDS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown fields {sorted(unknown)!r}")

    previous_status = problem.status
    for key, value in changes.items():
        if key == "title":
            title = (value or "").strip()
            if not title:
                raise HTTPException(status_code=400, detail="Title is required")
            problem.title = title
        elif key == "difficulty":
            problem.difficulty = parse_difficulty(value)
        elif key == "status":
            problem.status = parse_problem_status(value)
        elif key == "number":
            if value is not None and value <= 0:
                raise HTTPException(status_code=400, detail="Number must be positive")
            problem.number = value
        elif key == "confidence":
            if value is not None and not 1 <= value <= 5:
                raise HTTPException(status_code=400, detail="Confidence must be 1-5")
            problem.confidence = value
        elif key in ("slug", "url"):
            setattr(problem, key, _blank_to_none(value))
        elif key == "notes":
            problem.notes = value or ""
        elif key == "starred":
            problem.starred = bool(value)
        elif key == "tag_ids":
            known = {t.id for t in ctx.problem_source.list_tags()}
            missing = [t for t in value if t not in known]
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown tags {missing!r}")
            # Dedupe, keep a stable order.
            problem.tag_ids = sorted(set(value))

    now = datetime.now(UTC)
    if problem.status == ProblemStatus.SOLVED and problem.solved_at is None:
        problem.solved_at = now
    if problem.status == ProblemStatus.ATTEMPTED and problem.status != previous_status:
        problem.last_attempted_at = now


def list_problems(ctx: AppContext) -> list[dict[str, Any]]:
    return [problem_json(p) for p in ctx.problem_source.list_problems()]


def get_problem(ctx: AppContext, problem_id: str) -> dict[str, Any]:
    """One problem with its solutions and the tasks that practice it."""
    problem = _get_problem(ctx, problem_id)
    linked_tasks = [t for t in ctx.task_source.list_tasks() if t.problem_id == problem_id]
    return {
        **problem_json(problem),
        "solutions": [solution_json(s) for s in ctx.problem_source.list_solutions(problem_id)],
        "tasks": [task_json(t, ctx.task_source) for t in linked_tasks],
    }


def create_problem(ctx: AppContext, changes: dict[str, Any]) -> dict[str, Any]:
    if "title" not in changes or "difficulty" not in changes:
        raise HTTPException(status_code=400, detail="Title and difficulty are required")
    # Starts as To do, so a problem created as Attempted/Solved is a status
    # transition and gets its timestamp stamped like any other.
    problem = Problem(
        id=str(uuid.uuid4()),
        title=changes["title"],
        difficulty=parse_difficulty(changes["difficulty"]),
    )
    _apply_problem_changes(ctx, problem, changes)
    return problem_json(ctx.problem_source.create_problem(problem))


def update_problem(ctx: AppContext, problem_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    problem = _get_problem(ctx, problem_id)
    _apply_problem_changes(ctx, problem, changes)
    return problem_json(ctx.problem_source.update_problem(problem))


def delete_problem(ctx: AppContext, problem_id: str) -> None:
    """Delete a problem and its solutions; linked tasks are kept, un-linked
    (``on delete set null``)."""
    ctx.problem_source.delete_problem(problem_id)


# ---- Solutions --------------------------------------------------------------


def _validated_solution(solution: Solution) -> Solution:
    solution.title = solution.title.strip()
    if not solution.title:
        raise HTTPException(status_code=400, detail="Solution title is required")
    if not solution.language.strip():
        raise HTTPException(status_code=400, detail="Language is required")
    solution.time_complexity = _blank_to_none(solution.time_complexity)
    solution.space_complexity = _blank_to_none(solution.space_complexity)
    return solution


def create_solution(
    ctx: AppContext,
    problem_id: str,
    *,
    title: str,
    language: str,
    code: str,
    time_complexity: str | None,
    space_complexity: str | None,
    explanation: str,
    is_optimal: bool,
) -> dict[str, Any]:
    _get_problem(ctx, problem_id)
    solution = _validated_solution(
        Solution(
            id=str(uuid.uuid4()),
            problem_id=problem_id,
            title=title,
            language=language,
            code=code,
            time_complexity=time_complexity,
            space_complexity=space_complexity,
            explanation=explanation,
            is_optimal=is_optimal,
        )
    )
    return solution_json(ctx.problem_source.create_solution(solution))


def update_solution(
    ctx: AppContext,
    solution_id: str,
    *,
    title: str,
    language: str,
    code: str,
    time_complexity: str | None,
    space_complexity: str | None,
    explanation: str,
    is_optimal: bool,
) -> dict[str, Any]:
    existing = _get_solution(ctx, solution_id)
    solution = _validated_solution(
        dataclasses.replace(
            existing,
            title=title,
            language=language,
            code=code,
            time_complexity=time_complexity,
            space_complexity=space_complexity,
            explanation=explanation,
            is_optimal=is_optimal,
        )
    )
    return solution_json(ctx.problem_source.update_solution(solution))


def delete_solution(ctx: AppContext, solution_id: str) -> None:
    ctx.problem_source.delete_solution(solution_id)


# ---- Tags -------------------------------------------------------------------


def _tag_counts(ctx: AppContext) -> dict[str, int]:
    counts: dict[str, int] = {}
    for problem in ctx.problem_source.list_problems():
        for tag_id in problem.tag_ids:
            counts[tag_id] = counts.get(tag_id, 0) + 1
    return counts


def _check_tag_name(ctx: AppContext, name: str, *, exclude_id: str | None = None) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")
    for tag in ctx.problem_source.list_tags():
        if tag.id != exclude_id and tag.name.lower() == name.lower():
            raise HTTPException(status_code=409, detail=f"Tag {name!r} already exists")
    return name


def list_tags(ctx: AppContext) -> list[dict[str, Any]]:
    counts = _tag_counts(ctx)
    return [problem_tag_json(t, counts.get(t.id, 0)) for t in ctx.problem_source.list_tags()]


def create_tag(ctx: AppContext, *, name: str, color: str | None) -> dict[str, Any]:
    tag = ProblemTag(
        id=str(uuid.uuid4()), name=_check_tag_name(ctx, name), color=_blank_to_none(color)
    )
    return problem_tag_json(ctx.problem_source.create_tag(tag), 0)


def update_tag(ctx: AppContext, tag_id: str, *, name: str, color: str | None) -> dict[str, Any]:
    tag = ProblemTag(
        id=tag_id,
        name=_check_tag_name(ctx, name, exclude_id=tag_id),
        color=_blank_to_none(color),
    )
    try:
        updated = ctx.problem_source.update_tag(tag)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No tag {tag_id!r}") from exc
    return problem_tag_json(updated, _tag_counts(ctx).get(tag_id, 0))


def delete_tag(ctx: AppContext, tag_id: str) -> None:
    ctx.problem_source.delete_tag(tag_id)


# ---- Export -----------------------------------------------------------------


def export_problems(ctx: AppContext) -> dict[str, Any]:
    """Everything on the Problems tab as one JSON document, for backup."""
    problems = ctx.problem_source.list_problems()
    return {
        "exportedAt": datetime.now(UTC).isoformat(),
        "version": 1,
        "problems": [
            {
                **problem_json(p),
                "solutions": [solution_json(s) for s in ctx.problem_source.list_solutions(p.id)],
            }
            for p in problems
        ],
        "tags": list_tags(ctx),
    }
