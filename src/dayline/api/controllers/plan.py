"""HTTP controller for the plan endpoint."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from dayline.api.context import ContextDep
from dayline.api.services import plan as service

router = APIRouter()


@router.post("/api/plan")
def plan_day(day: date, ctx: ContextDep) -> dict[str, Any]:
    """Compute and commit the plan for ``day``.

    Each call reconciles rather than duplicates (including "Re-plan" clicks).
    """
    return service.plan_day(ctx, day)
