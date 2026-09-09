"""HTTP controller for planner-preferences endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import preferences as service

router = APIRouter()


class PreferencesUpdateRequest(BaseModel):
    peakHours: str | None = None
    categoryCaps: dict[str, int] | None = None
    standingRules: list[str] | None = None
    freeText: str | None = None


@router.get("/api/preferences")
def preferences_get(ctx: ContextDep) -> dict[str, Any]:
    """Current planner preferences (peak hours, caps, standing rules)."""
    return service.get_preferences_json(ctx)


@router.put("/api/preferences")
def preferences_put(
    body: PreferencesUpdateRequest, ctx: ContextDep
) -> dict[str, Any]:
    """Replace/merge planner preferences from a minimal settings surface."""
    patch = body.model_dump(exclude_unset=True)
    return service.patch_preferences_json(ctx, patch)
