"""Outcome-event orchestration (recent accept/reject/completion/override events)."""

from __future__ import annotations

from typing import Any

from dayline.adapters.outcomes import list_recent_outcomes
from dayline.api.context import AppContext


def list_outcomes(ctx: AppContext, limit: int = 20) -> list[dict[str, Any]]:
    return list_recent_outcomes(ctx.client, limit=max(1, min(limit, 100)))
