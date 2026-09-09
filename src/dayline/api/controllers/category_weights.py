"""HTTP controller for category focus-weight endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import category_weights as service

router = APIRouter()


@router.get("/api/category-weights")
def get_category_weights_endpoint(
    ctx: ContextDep,
) -> list[dict[str, Any]]:
    return service.get_category_weights_json(ctx)


class CategoryWeightItem(BaseModel):
    category: str
    rank: int


@router.put("/api/category-weights")
def put_category_weights(
    body: list[CategoryWeightItem], ctx: ContextDep
) -> list[dict[str, Any]]:
    return service.set_category_weights(ctx, [(item.category, item.rank) for item in body])


@router.post("/api/category-weights/apply")
def apply_category_weights(ctx: ContextDep) -> dict[str, int]:
    """Bulk-reprioritize every BACKLOG task to match the current category
    ranking. Explicit and opt-in - re-ranking weights alone never silently
    rewrites existing tasks (see ``adapters/category_weights.py``)."""
    return service.apply_category_weights(ctx)
