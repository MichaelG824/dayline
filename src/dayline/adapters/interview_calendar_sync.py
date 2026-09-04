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


def sync_interview_event(
    calendar: CalendarClient, interview: Interview, application: Application | None
) -> str:
    """Create a fresh calendar event for ``interview``; return its event id.

    If the interview already has a linked event (``interview.google_event_id``),
    delete it first - interviews have no edit endpoint today, so "update in
    place" isn't a case that exists yet; delete-then-recreate is simplest.
    """
    if interview.google_event_id:
        calendar.delete_event(interview.google_event_id)
    title = interview_event_title(interview, application)
    end = interview.scheduled_at + timedelta(minutes=INTERVIEW_EVENT_DURATION_MIN)
    return calendar.create_block(title, interview.scheduled_at, end)
