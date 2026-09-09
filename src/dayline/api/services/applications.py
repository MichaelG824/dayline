"""Application (job-funnel) orchestration over the Supabase application source."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from dayline.api.context import AppContext
from dayline.api.serializers import application_json, interview_json
from dayline.models import Application, ApplicationStage


def list_applications(ctx: AppContext) -> list[dict[str, Any]]:
    return [application_json(a) for a in ctx.application_source.list_applications()]


def list_application_interviews(
    ctx: AppContext, application_id: str
) -> list[dict[str, Any]]:
    return [
        interview_json(i, ctx.application_source)
        for i in ctx.interview_source.list_for_application(application_id)
    ]


def create_application(
    ctx: AppContext,
    *,
    company: str,
    role: str,
    stage: str | None = None,
    applied_at: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        stage_value = ApplicationStage(stage) if stage else ApplicationStage.APPLIED
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown stage {stage!r}") from exc

    application = Application(
        id=str(uuid.uuid4()),
        company=company,
        role=role,
        stage=stage_value,
        applied_at=datetime.fromisoformat(applied_at) if applied_at else None,
        notes=notes,
    )
    created = ctx.application_source.create_application(application)
    return application_json(created)
