"""Unit tests for the shared dict->Task mapping used by SupabaseTaskSource.

These exercise ``_dict_to_task`` directly (no network), which is where the
real translation risk lives: unknown enum values and missing fields must
degrade to safe defaults rather than breaking a whole plan.
"""

from __future__ import annotations

from dayline.adapters.task_source import DEFAULT_DURATION_MIN, _dict_to_task
from dayline.models import (
    Category,
    Priority,
    Recurrence,
    Status,
    Weekday,
    Window,
)


def test_dict_to_task_full_row() -> None:
    t = _dict_to_task(
        {
            "id": "abc",
            "name": "Study AI coding",
            "category": "AI Coding - React/Python",
            "priority": "P0",
            "status": "Backlog",
            "est_duration_min": 60,
            "fixed_time": None,
            "preferred_window": "Morning",
            "due_date": "2026-09-05",
            "recurs": "Weekly",
            "recur_day": "Sun",
        }
    )
    assert t.id == "abc"
    assert t.name == "Study AI coding"
    assert t.category == Category.AI_CODING_REACT_PYTHON
    assert t.priority == Priority.P0
    assert t.status == Status.BACKLOG
    assert t.est_duration_min == 60
    assert t.preferred_window == Window.MORNING
    assert t.due_date is not None and t.due_date.year == 2026
    assert t.recurs == Recurrence.WEEKLY
    assert t.recur_day == Weekday.SUN


def test_dict_to_task_missing_fields_get_safe_defaults() -> None:
    t = _dict_to_task(
        {"id": "x", "name": None, "category": None, "priority": None,
         "status": None, "est_duration_min": None}
    )
    assert t.name == "(untitled)"
    assert t.category == Category.OTHER
    assert t.priority == Priority.P3
    assert t.status == Status.BACKLOG
    assert t.est_duration_min == DEFAULT_DURATION_MIN
    assert t.recurs is None and t.recur_day is None


def test_dict_to_task_unknown_enum_values_are_ignored() -> None:
    t = _dict_to_task(
        {"id": "x", "name": "n", "category": "Nonsense", "priority": "P9",
         "status": "Weird", "est_duration_min": 10, "preferred_window": "Noon"}
    )
    assert t.category == Category.OTHER
    assert t.priority == Priority.P3
    assert t.status == Status.BACKLOG
    assert t.preferred_window is None


def test_dict_to_task_parses_fixed_time_datetime() -> None:
    t = _dict_to_task(
        {"id": "x", "name": "n", "category": "Leetcode", "priority": "P1",
         "status": "Scheduled", "est_duration_min": 45,
         "fixed_time": "2026-09-01T10:30:00"}
    )
    assert t.fixed_time is not None
    assert (t.fixed_time.hour, t.fixed_time.minute) == (10, 30)
