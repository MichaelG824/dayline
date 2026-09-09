"""HTTP controller for the outcomes endpoint (retros / debugging)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from dayline.api.context import ContextDep
from dayline.api.services import outcomes as service

router = APIRouter()


@router.get("/api/outcomes")
def outcomes_list(
    ctx: ContextDep, limit: int = 20
) -> list[dict[str, Any]]:
    """Recent outcome events for retros / debugging."""
    return service.list_outcomes(ctx, limit=limit)
