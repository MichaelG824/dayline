"""HTTP controller for task endpoints - thin: request models in, service out."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import tasks as service

router = APIRouter()


@router.get("/api/tasks")
def list_tasks(day: date, ctx: ContextDep) -> list[dict[str, Any]]:
    """All current tasks (with status/scheduled time)."""
    return service.list_tasks(ctx)


class TaskCreateRequest(BaseModel):
    name: str
    category: str
    estDurationMin: int
    priority: str | None = None
    plannedDate: str | None = None
    fixedTime: str | None = None
    preferredWindow: str | None = None
    dueDate: str | None = None
    recurs: str | None = None
    recurDay: str | None = None
    applicationId: str | None = None
    interviewId: str | None = None


@router.post("/api/tasks", status_code=201)
def create_task(
    body: TaskCreateRequest, ctx: ContextDep
) -> dict[str, Any]:
    return service.create_task(
        ctx,
        name=body.name,
        category=body.category,
        est_duration_min=body.estDurationMin,
        priority=body.priority,
        planned_date=body.plannedDate,
        fixed_time=body.fixedTime,
        preferred_window=body.preferredWindow,
        due_date=body.dueDate,
        recurs=body.recurs,
        recur_day=body.recurDay,
        application_id=body.applicationId,
        interview_id=body.interviewId,
    )


class TaskUpdateRequest(BaseModel):
    name: str | None = None
    estDurationMin: int | None = None
    priority: str | None = None
    plannedDate: str | None = None
    category: str | None = None
    status: str | None = None
    fixedTime: str | None = None


@router.patch("/api/tasks/{task_id}")
def update_task(
    task_id: str, body: TaskUpdateRequest, ctx: ContextDep
) -> dict[str, Any]:
    return service.update_task(
        ctx,
        task_id,
        name=body.name,
        est_duration_min=body.estDurationMin,
        priority=body.priority,
        planned_date=body.plannedDate,
        category=body.category,
        status=body.status,
        fixed_time=body.fixedTime,
    )


@router.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, ctx: ContextDep) -> None:
    service.delete_task(ctx, task_id)
