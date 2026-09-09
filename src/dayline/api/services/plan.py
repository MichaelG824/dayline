"""Plan orchestration: compute and commit a day's plan.

Thin wrapper over :func:`run_daily_plan` (which holds the scheduling logic) plus
serialization - no scheduling decisions live here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dayline.api.context import AppContext
from dayline.api.serializers import plan_json
from dayline.scheduler.run import AGENT_MARKER, run_daily_plan


def plan_day(ctx: AppContext, day: date) -> dict[str, Any]:
    """Compute and commit the plan for ``day`` (reconciles rather than duplicates)."""
    calendar = ctx.calendar(day)
    plan = run_daily_plan(
        day, ctx.task_source, calendar, interview_source=ctx.interview_source
    )
    agent_blocks = [
        e for e in calendar.list_events(day) if e.title.startswith(AGENT_MARKER)
    ]
    return {
        "day": day.isoformat(),
        **plan_json(plan, ctx.task_source),
        "agentBlockCount": len(agent_blocks),
    }
