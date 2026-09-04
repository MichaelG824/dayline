"""Push interviews to the real Google Calendar (one-way: Interview -> event).

Plain functions over the existing :class:`CalendarClient` Protocol, not a new
Protocol + adapter pair - same "simple glue, no scheduling logic" precedent as
``category_weights.py``. Fully testable against :class:`InMemoryCalendar`;
no real Google API needed.

Deliberately separate from the scheduler's day-keyed calendar
(``scheduler/run.py``, ``AGENT_MARKER``-tagged blocks): that calendar plans
*tasks* and stays in-memory. This module syncs *interviews* to whatever real
``CalendarClient`` the API layer connects (see ``api/main.py``).
"""

from __future__ import annotations

from datetime import timedelta

from dayline.adapters.calendar import CalendarClient
from dayline.models import Application, Interview

# Interview has no duration field - assume a standard hour for the calendar
# block. Good enough for a reminder; the interview itself may run shorter or
# longer.
INTERVIEW_EVENT_DURATION_MIN = 60


def interview_event_title(interview: Interview, application: Application | None) -> str:
    company = application.company if application else "Unknown company"
    return f"Interview: {company} ({interview.category.value})"


_TITLE_STOPWORDS = {"interview", "interviews", "with", "call", "screen", "screening", "round"}


def guess_company_from_title(title: str) -> str:
    """Best-effort company name guess from a calendar event title - e.g.
    "Interview with Acme" or "Acme interview" -> "Acme". Only used to
    pre-fill the import flow's editable company field, so an imperfect guess
    (or the unchanged title, if nothing is left after stripping filler
    words) is fine - the user can fix it before importing."""
    kept = [t for t in title.split() if t.strip(":,.-").lower() not in _TITLE_STOPWORDS]
    guess = " ".join(kept).strip()
    return guess or title


def sync_interview_event(
    calendar: CalendarClient, interview: Interview, application: Application | None
) -> str:
    """Create or update the calendar event for ``interview``; return its id.

    If the interview already has a linked event (``interview.google_event_id``),
    update it in place rather than deleting and recreating - the linked event
    may not be one the app created (an imported interview links to the
    user's own pre-existing event), so deleting it would destroy real
    calendar data (attendees, location, video links, ...) that can never be
    recovered. Only a brand-new interview gets a brand-new event.
    """
    title = interview_event_title(interview, application)
    end = interview.scheduled_at + timedelta(minutes=INTERVIEW_EVENT_DURATION_MIN)
    if interview.google_event_id:
        calendar.update_event(interview.google_event_id, title, interview.scheduled_at, end)
        return interview.google_event_id
    return calendar.create_block(title, interview.scheduled_at, end)
