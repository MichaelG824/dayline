"""HTTP controller for interview endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import interviews as service

router = APIRouter()


@router.get("/api/interviews")
def list_interviews(
    ctx: ContextDep, upcoming: bool = True
) -> list[dict[str, Any]]:
    return service.list_interviews(ctx, upcoming=upcoming)


@router.get("/api/interviews/hidden")
def list_hidden_interviews(
    ctx: ContextDep,
) -> list[dict[str, Any]]:
    return service.list_hidden_interviews(ctx)


@router.post("/api/interviews/{interview_id}/unhide")
def unhide_interview(
    interview_id: str, ctx: ContextDep
) -> dict[str, Any]:
    return service.unhide_interview(ctx, interview_id)


class InterviewCategoryUpdateRequest(BaseModel):
    category: str


@router.patch("/api/interviews/{interview_id}")
def update_interview_category(
    interview_id: str,
    body: InterviewCategoryUpdateRequest,
    ctx: ContextDep,
) -> dict[str, Any]:
    return service.update_interview_category(ctx, interview_id, body.category)


class InterviewCreateRequest(BaseModel):
    applicationId: str
    category: str
    scheduledAt: str
    notes: str | None = None


@router.post("/api/interviews", status_code=201)
def create_interview(
    body: InterviewCreateRequest, ctx: ContextDep
) -> dict[str, Any]:
    return service.create_interview(
        ctx,
        application_id=body.applicationId,
        category=body.category,
        scheduled_at=body.scheduledAt,
        notes=body.notes,
    )


@router.delete("/api/interviews/{interview_id}", status_code=204)
def delete_interview(interview_id: str, ctx: ContextDep) -> None:
    service.delete_interview(ctx, interview_id)
