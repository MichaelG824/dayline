"""Google Calendar connection + interview backfill orchestration.

The connected client is held on the shared :class:`AppContext` for the life of
the process (starts disconnected). Only interviews are pushed to a real
calendar - task blocks never are (see AGENTS.md).
"""

from __future__ import annotations

import contextlib

from fastapi import HTTPException

from dayline.adapters.calendar import GoogleCalendarClient
from dayline.adapters.interview_calendar_sync import sync_interview_event
from dayline.api.context import AppContext


def calendar_status(ctx: AppContext) -> dict[str, bool]:
    return {"connected": ctx.google_calendar is not None}


def connect_calendar(ctx: AppContext) -> dict[str, bool]:
    """Run the (one-time) Google OAuth flow and hold the connected client for
    the life of this process. Needs `credentials.json` at the repo root -
    see GOOGLE_SETUP.md."""
    try:
        ctx.google_calendar = GoogleCalendarClient()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"connected": True}


def sync_interviews(ctx: AppContext) -> dict[str, int]:
    """Push every currently-upcoming interview to the connected calendar -
    backfills interviews created before the calendar was connected."""
    if ctx.google_calendar is None:
        raise HTTPException(
            status_code=409, detail="Google Calendar is not connected yet."
        )
    synced = 0
    for interview in ctx.interview_source.list_upcoming():
        application = None
        with contextlib.suppress(KeyError):
            application = ctx.application_source.get_application(interview.application_id)
        had_event = interview.google_event_id is not None
        event_id = sync_interview_event(ctx.google_calendar, interview, application)
        if had_event:
            ctx.interview_source.update_interview(
                interview.id, google_event_id=event_id
            )
        else:
            # This call just created a fresh event - Dayline made it, so it
            # owns it (matches create_interview's own-event bookkeeping).
            ctx.interview_source.update_interview(
                interview.id, google_event_id=event_id, google_event_owned=True
            )
        synced += 1
    return {"synced": synced}
