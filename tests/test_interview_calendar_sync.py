"""Tests for pushing interviews to a real calendar (Interview -> event).

Uses :class:`InMemoryCalendar` as the ``CalendarClient`` fake - no real
Google API or mocking needed, since the sync logic only depends on the
Protocol surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from dayline.adapters.calendar import InMemoryCalendar
from dayline.adapters.interview_calendar_sync import (
    INTERVIEW_EVENT_DURATION_MIN,
    interview_event_title,
    sync_interview_event,
)
from dayline.models import Application, ApplicationStage, Interview, InterviewCategory

APPLICATION = Application(
    id="app-1", company="Acme", role="Backend Engineer", stage=ApplicationStage.ONSITE
)


def _interview(**overrides: object) -> Interview:
    defaults: dict[str, object] = {
        "id": "int-1",
        "application_id": "app-1",
        "category": InterviewCategory.SYSTEM_DESIGN,
        "scheduled_at": datetime(2026, 9, 10, 14, 0),
        "notes": None,
        "google_event_id": None,
    }
    defaults.update(overrides)
    return Interview(**defaults)  # type: ignore[arg-type]


def test_title_includes_company_and_category() -> None:
    title = interview_event_title(_interview(), APPLICATION)
    assert title == "Interview: Acme (System Design)"


def test_title_falls_back_when_application_missing() -> None:
    title = interview_event_title(_interview(), None)
    assert title == "Interview: Unknown company (System Design)"


def test_sync_creates_event_when_none_exists() -> None:
    calendar = InMemoryCalendar()
    interview = _interview()

    event_id = sync_interview_event(calendar, interview, APPLICATION)

    events = calendar.list_events(interview.scheduled_at.date())
    assert len(events) == 1
    assert events[0].event_id == event_id
    assert events[0].title == "Interview: Acme (System Design)"
    assert events[0].start == interview.scheduled_at
    assert events[0].end == interview.scheduled_at + timedelta(
        minutes=INTERVIEW_EVENT_DURATION_MIN
    )


def test_resync_deletes_old_event_and_creates_new() -> None:
    calendar = InMemoryCalendar()
    interview = _interview()

    first_id = sync_interview_event(calendar, interview, APPLICATION)
    interview.google_event_id = first_id
    second_id = sync_interview_event(calendar, interview, APPLICATION)

    assert second_id != first_id
    events = calendar.list_events(interview.scheduled_at.date())
    assert len(events) == 1
    assert events[0].event_id == second_id
