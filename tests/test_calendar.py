"""Tests for InMemoryCalendar.list_events_range - the calendar agenda view's
range query, exercised without any real Google API or mocking."""

from __future__ import annotations

from datetime import date, datetime

from dayline.adapters.calendar import CalendarEvent, InMemoryCalendar

RANGE_START = date(2026, 9, 10)
RANGE_END = date(2026, 9, 16)


def _event(event_id: str, start: datetime, end: datetime) -> CalendarEvent:
    return CalendarEvent(event_id, f"event {event_id}", start, end)


def test_event_fully_inside_range_is_included() -> None:
    ev = _event("a", datetime(2026, 9, 12, 10, 0), datetime(2026, 9, 12, 11, 0))
    calendar = InMemoryCalendar([ev])
    assert calendar.list_events_range(RANGE_START, RANGE_END) == [ev]


def test_event_fully_before_range_is_excluded() -> None:
    ev = _event("a", datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0))
    calendar = InMemoryCalendar([ev])
    assert calendar.list_events_range(RANGE_START, RANGE_END) == []


def test_event_fully_after_range_is_excluded() -> None:
    ev = _event("a", datetime(2026, 9, 20, 10, 0), datetime(2026, 9, 20, 11, 0))
    calendar = InMemoryCalendar([ev])
    assert calendar.list_events_range(RANGE_START, RANGE_END) == []


def test_event_overlapping_range_start_boundary_is_included() -> None:
    # Starts the day before the range but ends on the range's first day.
    ev = _event("a", datetime(2026, 9, 9, 22, 0), datetime(2026, 9, 10, 1, 0))
    calendar = InMemoryCalendar([ev])
    assert calendar.list_events_range(RANGE_START, RANGE_END) == [ev]


def test_event_overlapping_range_end_boundary_is_included() -> None:
    # Starts on the range's last day but ends the day after.
    ev = _event("a", datetime(2026, 9, 16, 22, 0), datetime(2026, 9, 17, 1, 0))
    calendar = InMemoryCalendar([ev])
    assert calendar.list_events_range(RANGE_START, RANGE_END) == [ev]


def test_results_are_sorted_by_start() -> None:
    later = _event("later", datetime(2026, 9, 14, 9, 0), datetime(2026, 9, 14, 10, 0))
    earlier = _event("earlier", datetime(2026, 9, 11, 9, 0), datetime(2026, 9, 11, 10, 0))
    calendar = InMemoryCalendar([later, earlier])
    assert calendar.list_events_range(RANGE_START, RANGE_END) == [earlier, later]
