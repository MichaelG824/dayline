"""Task CRUD orchestration over the Supabase task source.

Category-priority resolution for new tasks happens here (before the planner
core ever sees the task); best-effort outcome logging for retros happens here
too. Neither ever blocks the edit.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException

from dayline.adapters.category_weights import get_category_weights
from dayline.adapters.outcomes import (
    OUTCOME_DURATION_OVERRIDE,
    OUTCOME_TASK_COMPLETED,
    log_outcome,
)
from dayline.api.context import AppContext
from dayline.api.parsing import (
    parse_category,
    parse_priority,
    parse_recurrence,
    parse_status,
    parse_weekday,
    parse_window,
)
from dayline.api.serializers import task_json
from dayline.models import Priority, Status, Task


def list_tasks(ctx: AppContext) -> list[dict[str, Any]]:
    return [task_json(t, ctx.task_source) for t in ctx.task_source.list_tasks()]


def create_task(
    ctx: AppContext,
    *,
    name: str,
    category: str,
    est_duration_min: int,
    priority: str | None = None,
    planned_date: str | None = None,
    fixed_time: str | None = None,
    preferred_window: str | None = None,
    due_date: str | None = None,
    recurs: str | None = None,
    recur_day: str | None = None,
    application_id: str | None = None,
    interview_id: str | None = None,
) -> dict[str, Any]:
    cat = parse_category(category)
    if priority is not None:
        prio = parse_priority(priority)
    else:
        weights = get_category_weights(ctx.client)
        prio = weights.get(cat, Priority.P3)

    try:
        task = Task(
            id=str(uuid.uuid4()),
            name=name,
            category=cat,
            priority=prio,
            est_duration_min=est_duration_min,
            # A recurring task's eligibility is driven by recurs/recur_day, not
            # planned_date - ignore planned_date when recurrence is set so the
            # two mechanisms can't conflict (see Task.planned_date docstring).
            planned_date=(
                date.fromisoformat(planned_date)
                if planned_date and not recurs
                else None
            ),
            fixed_time=datetime.fromisoformat(fixed_time) if fixed_time else None,
            preferred_window=(
                parse_window(preferred_window) if preferred_window else None
            ),
            due_date=datetime.fromisoformat(due_date) if due_date else None,
            recurs=parse_recurrence(recurs) if recurs else None,
            recur_day=parse_weekday(recur_day) if recur_day else None,
            application_id=application_id,
            interview_id=interview_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    created = ctx.task_source.create_task(task)
    return task_json(created, ctx.task_source)


def update_task(
    ctx: AppContext,
    task_id: str,
    *,
    name: str | None = None,
    est_duration_min: int | None = None,
    priority: str | None = None,
    planned_date: str | None = None,
    category: str | None = None,
    status: str | None = None,
    fixed_time: str | None = None,
) -> dict[str, Any]:
    try:
        before = ctx.task_source.get_task(task_id)
        updated = ctx.task_source.update_task(
            task_id,
            name=name,
            status=parse_status(status) if status else None,
            est_duration_min=est_duration_min,
            priority=parse_priority(priority) if priority else None,
            planned_date=date.fromisoformat(planned_date) if planned_date else None,
            category=parse_category(category) if category else None,
            fixed_time=datetime.fromisoformat(fixed_time) if fixed_time else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No task {task_id!r}") from exc

    # Best-effort outcome log for retros (never blocks the edit).
    with contextlib.suppress(Exception):
        if est_duration_min is not None and est_duration_min != before.est_duration_min:
            log_outcome(
                ctx.client,
                OUTCOME_DURATION_OVERRIDE,
                {
                    "taskId": task_id,
                    "fromMin": before.est_duration_min,
                    "toMin": est_duration_min,
                },
            )
        if status == Status.DONE.value and before.status != Status.DONE:
            log_outcome(
                ctx.client,
                OUTCOME_TASK_COMPLETED,
                {"taskId": task_id, "name": updated.name, "category": updated.category.value},
            )
    return task_json(updated, ctx.task_source)


def delete_task(ctx: AppContext, task_id: str) -> None:
    """Delete a task outright - the next plan computation (which the frontend
    triggers via onTasksChanged) naturally reconciles the real calendar,
    since a deleted task is no longer eligible and drops out of the plan's
    blocks; no calendar-specific code is needed here."""
    ctx.task_source.delete_task(task_id)
