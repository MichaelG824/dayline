"""Task source interface + in-memory fake + Supabase-backed implementation.

``TaskSource`` is the contract the planner uses to read and update tasks.
:class:`InMemoryTaskSource` backs tests and local runs; :class:`SupabaseTaskSource`
is the real persistent backend.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol, TypeVar, runtime_checkable

from dayline.models import (
    Category,
    Priority,
    Recurrence,
    Status,
    Task,
    Weekday,
    Window,
)


@runtime_checkable
class TaskSource(Protocol):
    """Read/update/create surface over the task backlog."""

    def list_tasks(
        self,
        *,
        status: Status | None = None,
        category: Category | None = None,
    ) -> list[Task]:
        """Return tasks, optionally filtered by status and/or category."""
        ...

    def get_task(self, task_id: str) -> Task:
        """Return a single task by id. Raises ``KeyError`` if absent."""
        ...

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        status: Status | None = None,
        scheduled_time: datetime | None = None,
        est_duration_min: int | None = None,
        priority: Priority | None = None,
        planned_date: date | None = None,
        category: Category | None = None,
        fixed_time: datetime | None = None,
    ) -> Task:
        """Update any of the given fields on a task; return the new state."""
        ...

    def create_task(self, task: Task) -> Task:
        """Persist a new task; return it as stored."""
        ...

    def delete_task(self, task_id: str) -> None:
        """Delete a task by id. No-op if it is already gone."""
        ...


class InMemoryTaskSource:
    """A fully working in-memory :class:`TaskSource` for tests, local runs, and
    the Streamlit dashboard - no network, no credentials.

    Copies are returned on read so callers can't mutate internal state by
    accident (mirrors the isolation a real API boundary gives you).
    """

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        # scheduled_time is not a field on Task; the Supabase schema stores it
        # separately (its own column), so the fake tracks it on the side too.
        self._scheduled_time: dict[str, datetime] = {}
        for task in tasks or []:
            self._tasks[task.id] = copy.deepcopy(task)

    def list_tasks(
        self,
        *,
        status: Status | None = None,
        category: Category | None = None,
    ) -> list[Task]:
        result = [
            copy.deepcopy(t)
            for t in self._tasks.values()
            if (status is None or t.status == status)
            and (category is None or t.category == category)
        ]
        # Stable order for deterministic downstream behavior.
        result.sort(key=lambda t: t.id)
        return result

    def get_task(self, task_id: str) -> Task:
        return copy.deepcopy(self._tasks[task_id])

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        status: Status | None = None,
        scheduled_time: datetime | None = None,
        est_duration_min: int | None = None,
        priority: Priority | None = None,
        planned_date: date | None = None,
        category: Category | None = None,
        fixed_time: datetime | None = None,
    ) -> Task:
        task = self._tasks[task_id]  # KeyError if unknown, matching the contract
        if name is not None:
            task.name = name
        if status is not None:
            task.status = status
        if scheduled_time is not None:
            self._scheduled_time[task_id] = scheduled_time
        if est_duration_min is not None:
            task.est_duration_min = est_duration_min
        if priority is not None:
            task.priority = priority
        if planned_date is not None:
            task.planned_date = planned_date
        if category is not None:
            task.category = category
        if fixed_time is not None:
            task.fixed_time = fixed_time
        return copy.deepcopy(task)

    def create_task(self, task: Task) -> Task:
        self._tasks[task.id] = copy.deepcopy(task)
        return copy.deepcopy(task)

    def delete_task(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        self._scheduled_time.pop(task_id, None)

    # Convenience for tests/UI - not part of the Protocol.
    def scheduled_time_of(self, task_id: str) -> datetime | None:
        """Return the last scheduled time recorded for a task, if any."""
        return self._scheduled_time.get(task_id)


# Fallback duration (minutes) for a row with no duration set, so such a task
# can still be scheduled instead of failing Task construction.
DEFAULT_DURATION_MIN = 30


# --------------------------------------------------------------------------- #
# dict (from Supabase or any other row-shaped source) -> domain Task
# --------------------------------------------------------------------------- #
_E = TypeVar("_E", bound=Enum)


def _dict_to_task(d: dict[str, Any]) -> Task:
    """Map a task dict into a domain :class:`Task`.

    Unknown enum values and missing fields degrade to safe defaults rather than
    raising, so one malformed row can't break a whole plan.
    """
    duration = d.get("est_duration_min")
    return Task(
        id=d["id"],
        name=d.get("name") or "(untitled)",
        category=_opt_enum(Category, d.get("category")) or Category.OTHER,
        priority=_priority(d.get("priority")),
        est_duration_min=int(duration) if duration else DEFAULT_DURATION_MIN,
        status=_opt_enum(Status, d.get("status")) or Status.BACKLOG,
        fixed_time=_parse_dt(d.get("fixed_time")),
        preferred_window=_opt_enum(Window, d.get("preferred_window")),
        due_date=_parse_dt(d.get("due_date")),
        planned_date=_parse_date(d.get("planned_date")),
        recurs=_opt_enum(Recurrence, d.get("recurs")),
        recur_day=_opt_enum(Weekday, d.get("recur_day")),
        application_id=d.get("application_id"),
        interview_id=d.get("interview_id"),
    )


def _opt_enum(enum_cls: type[_E], value: Any) -> _E | None:
    """Coerce ``value`` into ``enum_cls`` by value, or ``None`` if unknown."""
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _priority(value: Any) -> Priority:
    """Priority arrives as a name ('P0'..'P3'); default to lowest."""
    if not value:
        return Priority.P3
    try:
        return Priority[value]
    except KeyError:
        return Priority.P3


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    # The planning core is naive-local throughout (TimeSlot arithmetic
    # compares raw wall-clock digits with no timezone conversion anywhere -
    # see AGENTS.md), but fixed_time/due_date live in a Postgres timestamptz
    # column, which always round-trips as timezone-aware. Nothing in this
    # path ever performs a real timezone conversion (unlike the interview
    # scheduling fix, which does): both write and read treat the digits as
    # local time verbatim, so stripping the tzinfo Postgres adds is the
    # correct inverse of writing a naive string in the first place - not
    # stripping it crashes any TimeSlot comparison with "can't compare
    # offset-naive and offset-aware datetimes".
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Supabase-backed TaskSource
# --------------------------------------------------------------------------- #


def _task_to_row(task: Task) -> dict[str, Any]:
    """Map a domain :class:`Task` into a Supabase ``tasks`` row for insert."""
    return {
        "id": task.id,
        "name": task.name,
        "category": task.category.value,
        "priority": task.priority.name,
        "est_duration_min": task.est_duration_min,
        "status": task.status.value,
        "fixed_time": task.fixed_time.isoformat() if task.fixed_time else None,
        "preferred_window": task.preferred_window.value if task.preferred_window else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "planned_date": task.planned_date.isoformat() if task.planned_date else None,
        "recurs": task.recurs.value if task.recurs else None,
        "recur_day": task.recur_day.value if task.recur_day else None,
        "application_id": task.application_id,
        "interview_id": task.interview_id,
    }


class SupabaseTaskSource:
    """Real Supabase-backed :class:`TaskSource` - the persistent replacement
    for :class:`InMemoryTaskSource` once credentials are configured.

    Needs the ``supabase`` package and a client constructed via
    :func:`dayline.adapters.supabase_client.get_supabase_client`.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def list_tasks(
        self,
        *,
        status: Status | None = None,
        category: Category | None = None,
    ) -> list[Task]:
        query = self._client.table("tasks").select("*")
        if status is not None:
            query = query.eq("status", status.value)
        if category is not None:
            query = query.eq("category", category.value)
        resp = query.execute()
        return [_dict_to_task(row) for row in resp.data]

    def get_task(self, task_id: str) -> Task:
        resp = self._client.table("tasks").select("*").eq("id", task_id).execute()
        if not resp.data:
            raise KeyError(task_id)
        return _dict_to_task(resp.data[0])

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        status: Status | None = None,
        scheduled_time: datetime | None = None,
        est_duration_min: int | None = None,
        priority: Priority | None = None,
        planned_date: date | None = None,
        category: Category | None = None,
        fixed_time: datetime | None = None,
    ) -> Task:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if status is not None:
            updates["status"] = status.value
        if scheduled_time is not None:
            # scheduled_time isn't a Task dataclass field (mirrors
            # InMemoryTaskSource, which tracks it on the side too) - it has
            # its own column, distinct from fixed_time (an immutable anchor
            # the planner re-reads every run; overwriting it with the
            # *outcome* of a flexible placement would wrongly pin the task
            # in all future runs).
            updates["scheduled_time"] = scheduled_time.isoformat()
        if est_duration_min is not None:
            updates["est_duration_min"] = est_duration_min
        if priority is not None:
            updates["priority"] = priority.name
        if planned_date is not None:
            updates["planned_date"] = planned_date.isoformat()
        if category is not None:
            updates["category"] = category.value
        if fixed_time is not None:
            updates["fixed_time"] = fixed_time.isoformat()
        resp = (
            self._client.table("tasks").update(updates).eq("id", task_id).execute()
        )
        if not resp.data:
            raise KeyError(task_id)
        return _dict_to_task(resp.data[0])

    def create_task(self, task: Task) -> Task:
        resp = self._client.table("tasks").insert(_task_to_row(task)).execute()
        return _dict_to_task(resp.data[0])

    def delete_task(self, task_id: str) -> None:
        self._client.table("tasks").delete().eq("id", task_id).execute()

    # Convenience for the API layer - not part of the Protocol, matching
    # InMemoryTaskSource's `scheduled_time_of`.
    def scheduled_time_of(self, task_id: str) -> datetime | None:
        resp = (
            self._client.table("tasks")
            .select("scheduled_time")
            .eq("id", task_id)
            .execute()
        )
        if not resp.data or not resp.data[0].get("scheduled_time"):
            return None
        return _parse_dt(resp.data[0]["scheduled_time"])
