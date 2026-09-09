"""Chat orchestration: build ChatDeps from the other services and drive the
analysis-first propose/confirm flow.

The LLM tool loop itself lives in ``api/chat.py`` (unchanged). This module only
wires that module's read/write callbacks to the live services and adapters, and
owns the confirm path (apply approved proposals, log accept/reject outcomes,
re-plan the day). ``POST /api/chat/confirm`` is the only mutation path - never
auto-apply because Claude called a tool.
"""

from __future__ import annotations

import contextlib
from datetime import date
from typing import Any

from fastapi import HTTPException

from dayline.adapters.category_weights import set_category_ranks
from dayline.adapters.outcomes import (
    OUTCOME_DURATION_OVERRIDE,
    OUTCOME_PROPOSAL_ACCEPTED,
    OUTCOME_PROPOSAL_REJECTED,
    log_outcome,
)
from dayline.adapters.preferences import get_preferences, patch_preferences
from dayline.api.chat import ChatDeps, apply_proposal, run_chat_turn
from dayline.api.context import AppContext
from dayline.api.parsing import parse_category
from dayline.api.serializers import interview_json
from dayline.api.services import interviews as interview_service
from dayline.api.services import outcomes as outcome_service
from dayline.api.services.category_weights import get_category_weights_json
from dayline.api.services.plan import plan_day


def _chat_list_interviews(ctx: AppContext) -> list[dict[str, Any]]:
    interview_service.reconcile_calendar_interviews(ctx)
    return [
        interview_json(i, ctx.application_source)
        for i in ctx.interview_source.list_upcoming()
    ]


def _apply_category_ranks(
    ctx: AppContext, ranks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    mapping = {parse_category(item["category"]): int(item["rank"]) for item in ranks}
    set_category_ranks(ctx.client, mapping)
    return get_category_weights_json(ctx)


def build_chat_deps(ctx: AppContext) -> ChatDeps:
    return ChatDeps(
        task_source=ctx.task_source,
        get_plan=lambda day: plan_day(ctx, day),
        list_interviews=lambda: _chat_list_interviews(ctx),
        get_category_ranks=lambda: get_category_weights_json(ctx),
        get_preferences=lambda: get_preferences(ctx.client).to_dict(),
        get_recent_outcomes=lambda limit: outcome_service.list_outcomes(ctx, limit),
        apply_preference_update=lambda patch: patch_preferences(
            ctx.client, patch
        ).to_dict(),
        apply_category_ranks=lambda ranks: _apply_category_ranks(ctx, ranks),
        preferences_snapshot=get_preferences(ctx.client).to_dict(),
    )


def run_chat(
    ctx: AppContext,
    day: date,
    message: str,
    history: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Analysis-first assistant. Never applies changes directly - see
    ``api/chat.py`` for the propose/confirm split. Proposals may be empty."""
    result = run_chat_turn(
        ctx.anthropic_client,
        build_chat_deps(ctx),
        day,
        message,
        history=history,
    )
    return {
        "explanation": result.explanation,
        "proposals": result.proposals,
        "history": result.history,
    }


def confirm_chat(
    ctx: AppContext,
    day: date,
    proposals: list[dict[str, Any]],
    offered: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Apply the user-approved subset of a chat turn's proposals, log
    accept/reject outcomes, then re-plan the day."""
    deps = build_chat_deps(ctx)
    applied: list[dict[str, Any]] = []
    try:
        for p in proposals:
            result = apply_proposal(deps, p)
            applied.append(result)
            with contextlib.suppress(Exception):
                log_outcome(
                    ctx.client,
                    OUTCOME_PROPOSAL_ACCEPTED,
                    {"proposalType": p.get("type"), "proposal": p, "result": result},
                )
                if p.get("type") == "propose_duration_change":
                    log_outcome(
                        ctx.client,
                        OUTCOME_DURATION_OVERRIDE,
                        {
                            "taskId": p.get("task_id"),
                            "toMin": p.get("new_duration_min"),
                            "via": "chat_confirm",
                        },
                    )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    accepted_ids = {p.get("id") for p in proposals}
    for p in offered or []:
        if p.get("id") in accepted_ids:
            continue
        with contextlib.suppress(Exception):
            log_outcome(
                ctx.client,
                OUTCOME_PROPOSAL_REJECTED,
                {"proposalType": p.get("type"), "proposal": p},
            )

    plan_response = plan_day(ctx, day)
    return {"applied": applied, "plan": plan_response}
