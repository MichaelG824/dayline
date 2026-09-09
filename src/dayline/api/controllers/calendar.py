"""HTTP controller for Google Calendar connection endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from dayline.api.context import ContextDep
from dayline.api.services import calendar as service

router = APIRouter()


@router.get("/api/calendar/status")
def calendar_status(ctx: ContextDep) -> dict[str, bool]:
    return service.calendar_status(ctx)


@router.post("/api/calendar/connect")
def connect_calendar(ctx: ContextDep) -> dict[str, bool]:
    """Run the (one-time) Google OAuth flow and hold the connected client for
    the life of this process. Needs `credentials.json` at the repo root -
    see GOOGLE_SETUP.md."""
    return service.connect_calendar(ctx)


@router.post("/api/calendar/sync-interviews")
def sync_interviews(ctx: ContextDep) -> dict[str, int]:
    """Push every currently-upcoming interview to the connected calendar -
    backfills interviews created before the calendar was connected."""
    return service.sync_interviews(ctx)
