"""Shared test fixtures/builders.

Small helpers so tests read as intent ("a P1 behavioral task in the morning")
rather than datetime plumbing. Kept dependency-free.
"""

from __future__ import annotations

from datetime import date, datetime, time

from dayline.models import (
    Category,
    Priority,
    Recurrence,
    Task,
    TimeSlot,
    Weekday,
    Window,
)

DAY = date(2026, 8, 31)


def at(hour: int, minute: int = 0, *, day: date = DAY) -> datetime:
    """A datetime on ``day`` at the given wall-clock time."""
    return datetime.combine(day, time(hour=hour, minute=minute))


def slot(start_h: int, end_h: int, *, day: date = DAY) -> TimeSlot:
    """A free/busy TimeSlot spanning ``[start_h, end_h)`` on ``day``."""
    return TimeSlot(at(start_h, day=day), at(end_h, day=day))


def task(
    id: str,
    *,
    name: str | None = None,
    category: Category = Category.OTHER,
    priority: Priority = Priority.P2,
    duration: int = 60,
    fixed_time: datetime | None = None,
    preferred_window: Window | None = None,
    recurs: Recurrence | None = None,
    recur_day: Weekday | None = None,
    planned_date: date | None = None,
    interview_id: str | None = None,
) -> Task:
    """Build a Task with sensible defaults; override only what the test cares
    about."""
    return Task(
        name=name or id,
        category=category,
        priority=priority,
        est_duration_min=duration,
        id=id,
        fixed_time=fixed_time,
        preferred_window=preferred_window,
        recurs=recurs,
        recur_day=recur_day,
        planned_date=planned_date,
        interview_id=interview_id,
    )
