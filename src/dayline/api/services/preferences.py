"""Planner-preferences orchestration (peak hours, caps, standing rules)."""

from __future__ import annotations

from typing import Any

from dayline.adapters.preferences import get_preferences, patch_preferences
from dayline.api.context import AppContext


def get_preferences_json(ctx: AppContext) -> dict[str, Any]:
    return get_preferences(ctx.client).to_dict()


def patch_preferences_json(ctx: AppContext, patch: dict[str, Any]) -> dict[str, Any]:
    return patch_preferences(ctx.client, patch).to_dict()
