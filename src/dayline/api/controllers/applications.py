"""HTTP controller for application (job-funnel) endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import applications as service

router = APIRouter()


@router.get("/api/applications")
def list_applications(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_applications(ctx)


@router.get("/api/applications/{application_id}/interviews")
def list_application_interviews(
    application_id: str, ctx: ContextDep
) -> list[dict[str, Any]]:
    return service.list_application_interviews(ctx, application_id)


class ApplicationCreateRequest(BaseModel):
    company: str
    role: str
    stage: str | None = None
    appliedAt: str | None = None
    notes: str | None = None


@router.post("/api/applications", status_code=201)
def create_application(
    body: ApplicationCreateRequest, ctx: ContextDep
) -> dict[str, Any]:
    return service.create_application(
        ctx,
        company=body.company,
        role=body.role,
        stage=body.stage,
        applied_at=body.appliedAt,
        notes=body.notes,
    )
