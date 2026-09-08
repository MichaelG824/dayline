"""Unit tests for chat proposal apply helpers (no Anthropic call)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.chat import ChatDeps, apply_proposal, parse_category
from dayline.models import Category, Priority


def _deps(source: InMemoryTaskSource) -> ChatDeps:
    empty: list[dict[str, Any]] = []
    return ChatDeps(
        task_source=source,
        get_plan=lambda _d: {"day": date.today().isoformat(), "brief": "", "blocks": [], "unplaced": []},
        list_interviews=lambda: empty,
        get_category_ranks=lambda: empty,
        get_preferences=lambda: {},
        get_recent_outcomes=lambda _n: empty,
    )


def test_parse_category_exact_and_alias() -> None:
    assert parse_category("Behavioral") is Category.BEHAVIORAL
    assert parse_category("Interview Prep") is Category.BEHAVIORAL
    assert parse_category("system design") is Category.SYSTEM_DESIGN
    with pytest.raises(ValueError, match="Unknown category"):
        parse_category("Not A Real Category")


def test_apply_new_task_accepts_interview_prep_alias() -> None:
    src = InMemoryTaskSource()
    result = apply_proposal(
        _deps(src),
        {
            "type": "propose_new_task",
            "name": "Behavioral interview prep",
            "category": "Interview Prep",
            "est_duration_min": 60,
            "reason": "test",
        },
    )
    assert result["result"] == "ok"
    created = src.get_task(result["task_id"])
    assert created.category is Category.BEHAVIORAL
    assert created.est_duration_min == 60
    assert created.priority is Priority.P3
