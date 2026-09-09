"""Category focus-weight orchestration.

Re-ranking the weights never silently rewrites existing tasks; ``apply`` is the
explicit, separate action that bulk-reprioritizes BACKLOG tasks only (see
``adapters/category_weights.py`` and AGENTS.md).
"""

from __future__ import annotations

from typing import Any

from dayline.adapters.category_weights import (
    PREP_CATEGORIES,
    get_category_ranks,
    get_category_weights,
    set_category_ranks,
)
from dayline.api.context import AppContext
from dayline.api.parsing import parse_category
from dayline.models import Status


def get_category_weights_json(ctx: AppContext) -> list[dict[str, Any]]:
    ranks = get_category_ranks(ctx.client)
    return [{"category": c.value, "rank": ranks[c]} for c in PREP_CATEGORIES]


def set_category_weights(
    ctx: AppContext, items: list[tuple[str, int]]
) -> list[dict[str, Any]]:
    mapping = {parse_category(category): rank for category, rank in items}
    set_category_ranks(ctx.client, mapping)
    return get_category_weights_json(ctx)


def apply_category_weights(ctx: AppContext) -> dict[str, int]:
    """Bulk-reprioritize every BACKLOG task to match the current category ranking."""
    weights = get_category_weights(ctx.client)
    updated = 0
    for task in ctx.task_source.list_tasks(status=Status.BACKLOG):
        new_priority = weights.get(task.category)
        if new_priority is not None and new_priority != task.priority:
            ctx.task_source.update_task(task.id, priority=new_priority)
            updated += 1
    return {"updated": updated}
