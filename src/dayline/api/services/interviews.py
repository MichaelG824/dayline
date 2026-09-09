"""Interview orchestration - the calendar is the source of truth, not Supabase.

``reconcile_calendar_interviews`` runs before every read: calendar events in the
discovery window with no linked Interview row get one auto-created; already-linked
ones have their time refreshed from the live event (that is the entire reschedule
mechanism). Company/category are set once and never overwritten, so a user's
correction survives. See AGENTS.md for the ownership/hide semantics.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from dayline.adapters.category_weights import get_category_ranks
from dayline.adapters.interview_calendar_sync import (
    guess_company_from_title,
    sync_interview_event,
)
from dayline.api.context import INTERVIEW_DISCOVERY_WINDOW_DAYS, AppContext
from dayline.api.parsing import parse_interview_category
from dayline.api.serializers import interview_json
from dayline.models import Application, Interview, InterviewCategory
from dayline.scheduler.run import AGENT_MARKER


def reconcile_calendar_interviews(ctx: AppContext) -> None:
    """Auto-discover tracked interviews from the real calendar and keep
    already-linked ones' times in sync with it - the calendar is the source
    of truth for *when*, so "rescheduling" is just moving the event there.
    Company/category are set once and never overwritten, so a user's
    correction survives. Best-effort: never raises, since a Google hiccup
    must not break loading the Interviews tab."""
    if ctx.google_calendar is None:
        return
    today = date.today()
    end_day = today + timedelta(days=INTERVIEW_DISCOVERY_WINDOW_DAYS)
    tz = ZoneInfo(ctx.google_calendar.timezone)

    # after=start of today, include_hidden=True: a hidden interview's event
    # must still count as "already linked" or it would be rediscovered.
    tracked = ctx.interview_source.list_upcoming(
        after=datetime.combine(today, datetime.min.time()), include_hidden=True
    )
    by_event_id = {i.google_event_id: i for i in tracked if i.google_event_id}

    ranks = get_category_ranks(ctx.client)
    top_category = min(ranks, key=lambda c: ranks[c])
    default_category = InterviewCategory(top_category.value)

    for event in ctx.google_calendar.list_events_range(today, end_day):
        if event.title.startswith(AGENT_MARKER):
            continue
        start = event.start.replace(tzinfo=tz)
        existing = by_event_id.get(event.event_id)
        if existing is None:
            application = ctx.application_source.create_application(
                Application(
                    id=str(uuid.uuid4()),
                    company=guess_company_from_title(event.title),
                    role="",
                )
            )
            ctx.interview_source.create_interview(
                Interview(
                    id=str(uuid.uuid4()),
                    application_id=application.id,
                    category=default_category,
                    scheduled_at=start,
                    google_event_id=event.event_id,
                    google_event_owned=False,
                )
            )
        elif not existing.hidden and existing.scheduled_at != start:
            ctx.interview_source.set_scheduled_at(existing.id, start)


def list_interviews(ctx: AppContext, upcoming: bool = True) -> list[dict[str, Any]]:
    with contextlib.suppress(Exception):
        reconcile_calendar_interviews(ctx)
    after = datetime.now() if upcoming else datetime.min
    return [
        interview_json(i, ctx.application_source)
        for i in ctx.interview_source.list_upcoming(after=after)
    ]


def list_hidden_interviews(ctx: AppContext) -> list[dict[str, Any]]:
    return [
        interview_json(i, ctx.application_source)
        for i in ctx.interview_source.list_hidden()
    ]


def unhide_interview(ctx: AppContext, interview_id: str) -> dict[str, Any]:
    try:
        updated = ctx.interview_source.unhide_interview(interview_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"No interview {interview_id!r}"
        ) from exc
    return interview_json(updated, ctx.application_source)


def update_interview_category(
    ctx: AppContext, interview_id: str, category: str
) -> dict[str, Any]:
    cat = parse_interview_category(category)
    try:
        updated = ctx.interview_source.set_category(interview_id, cat)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"No interview {interview_id!r}"
        ) from exc
    if ctx.google_calendar is not None and updated.google_event_id:
        with contextlib.suppress(Exception):
            application = None
            with contextlib.suppress(KeyError):
                application = ctx.application_source.get_application(
                    updated.application_id
                )
            sync_interview_event(ctx.google_calendar, updated, application)
    return interview_json(updated, ctx.application_source)


def create_interview(
    ctx: AppContext,
    *,
    application_id: str,
    category: str,
    scheduled_at: str,
    notes: str | None = None,
) -> dict[str, Any]:
    cat = parse_interview_category(category)
    try:
        ctx.application_source.get_application(application_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"No application {application_id!r}"
        ) from exc

    interview = Interview(
        id=str(uuid.uuid4()),
        application_id=application_id,
        category=cat,
        scheduled_at=datetime.fromisoformat(scheduled_at),
        notes=notes,
    )
    created = ctx.interview_source.create_interview(interview)
    if ctx.google_calendar is not None:
        # Best-effort: a calendar hiccup must never fail interview creation -
        # Supabase remains the source of truth.
        with contextlib.suppress(Exception):
            application = None
            with contextlib.suppress(KeyError):
                application = ctx.application_source.get_application(
                    created.application_id
                )
            event_id = sync_interview_event(ctx.google_calendar, created, application)
            # This call always creates a fresh event (created.google_event_id
            # was None going in) - Dayline made it, so it owns it.
            created = ctx.interview_source.update_interview(
                created.id, google_event_id=event_id, google_event_owned=True
            )
    return interview_json(created, ctx.application_source)


def delete_interview(ctx: AppContext, interview_id: str) -> None:
    with contextlib.suppress(KeyError):
        interview = ctx.interview_source.get_interview(interview_id)
        if interview.google_event_id and not interview.google_event_owned:
            # Discovered/imported from an event Dayline doesn't own - dismiss
            # the tracking only, never touch the user's real calendar event.
            ctx.interview_source.hide_interview(interview_id)
            return
        if interview.google_event_id and ctx.google_calendar is not None:
            with contextlib.suppress(Exception):
                ctx.google_calendar.delete_event(interview.google_event_id)
        ctx.interview_source.delete_interview(interview_id)
