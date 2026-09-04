"""Scheduler entrypoint (Subtask 5).

``run_daily_plan`` is the seam the future morning cron sits on: it pulls open
tasks, reads the calendar, computes free time, calls the pure planning core, then
writes the plan back - creating calendar blocks and flipping tasks to
``SCHEDULED`` with their times - and returns the :class:`Plan`.

**Idempotency.** Every calendar block the agent creates is titled with a stable
:data:`AGENT_MARKER` prefix. At the start of each run the scheduler deletes its
own prior blocks for that day *before* reading busy time and re-planning, so a
re-run reconciles to the same plan with no duplicate events. Because open tasks
(anything not ``DONE``) are re-read each run, the second run reproduces the first
run's plan exactly.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time

from dayline.adapters.calendar import CalendarClient
from dayline.adapters.interview_source import InterviewSource
from dayline.adapters.task_source import TaskSource
from dayline.models import (
    Interview,
    Plan,
    Priority,
    Recurrence,
    ScheduledBlock,
    Status,
    Task,
    TimeSlot,
    Weekday,
)
from dayline.planner.core import build_plan

# Stable marker prefixed onto every agent-created calendar block title. This is
# the idempotency anchor: it identifies "these are my events" so re-runs clear
# and recreate them instead of duplicating. Safe to rename freely since
# CalendarClient is in-memory only today (nothing persists across restarts to
# reconcile against); a future real, persisted CalendarClient would need a
# one-time migration pass for any old-marker events before changing this.
AGENT_MARKER = "[dayline] "

# Default bounds of a planning day (local time). Tasks are packed into free time
# inside this window.
DEFAULT_DAY_START_HOUR = 8
DEFAULT_DAY_END_HOUR = 22

# A task linked to an interview scheduled within this many days gets its
# effective priority bumped one level for that planning run (see
# `_bump_for_interview_proximity`).
INTERVIEW_PROXIMITY_DAYS = 3


def run_daily_plan(
    day: date,
    task_source: TaskSource,
    calendar: CalendarClient,
    *,
    interview_source: InterviewSource | None = None,
    day_start_hour: int = DEFAULT_DAY_START_HOUR,
    day_end_hour: int = DEFAULT_DAY_END_HOUR,
    marker: str = AGENT_MARKER,
) -> Plan:
    """Compute and commit today's plan; return it.

    Depends only on the :class:`TaskSource` and :class:`CalendarClient`
    interfaces - never a concrete Supabase/Google class - so the real adapters
    drop in unchanged. ``interview_source`` is optional (defaults to ``None``,
    which disables the interview-proximity priority bump) so existing callers
    are unaffected.
    """
    # 1. Reconcile: clear our own prior blocks for the day first, so busy time
    #    below reflects only events we must plan *around*, and re-runs don't stack.
    _delete_marker_blocks(calendar, day, marker)

    # 2. Read the world after reconciliation.
    busy = calendar.list_busy(day)
    open_tasks = _eligible_tasks(day, task_source)
    if interview_source is not None:
        open_tasks = _bump_for_interview_proximity(open_tasks, interview_source, day)

    # 3. Pure planning.
    free = _compute_free(day, busy, day_start_hour, day_end_hour)
    plan = build_plan(open_tasks, free, day)

    # 4. Write-back: calendar blocks (marker-tagged) + task status/time.
    _write_blocks(calendar, plan.blocks, marker)
    for block in plan.blocks:
        task_source.update_task(
            block.task_id, status=Status.SCHEDULED, scheduled_time=block.start
        )

    return plan


def _delete_marker_blocks(calendar: CalendarClient, day: date, marker: str) -> None:
    """Delete every marker-tagged block on ``day`` - the idempotency half of
    the reconciliation, reused by both the in-memory scheduling calendar and
    :func:`sync_plan_to_calendar`'s push to a real calendar."""
    for event in calendar.list_events(day):
        if event.title.startswith(marker):
            calendar.delete_event(event.event_id)


def _write_blocks(
    calendar: CalendarClient, blocks: list[ScheduledBlock], marker: str
) -> None:
    """Create one marker-tagged calendar block per placed block."""
    for block in blocks:
        calendar.create_block(f"{marker}{block.title}", block.start, block.end)


def sync_plan_to_calendar(
    calendar: CalendarClient, day: date, plan: Plan, marker: str = AGENT_MARKER
) -> None:
    """Push an already-computed plan's blocks to ``calendar`` (delete prior
    marker-tagged blocks for ``day``, then create fresh ones) - the same
    idempotent reconciliation :func:`run_daily_plan` does internally, exposed
    standalone so a *second*, real calendar can mirror the plan without being
    the calendar :func:`run_daily_plan` itself reads busy time from or plans
    against. Intended for a best-effort push once planning (against the fast,
    reliable in-memory calendar) has already completed - see ``api/main.py``.
    """
    _delete_marker_blocks(calendar, day, marker)
    _write_blocks(calendar, plan.blocks, marker)


def is_due(recurs: Recurrence, recur_day: Weekday | None, day: date) -> bool:
    """Whether a recurring task should be planned on ``day``.

    A pure function of the date, so eligibility is deterministic and a same-day
    re-run is stable:

    * ``DAILY``    - every day.
    * ``WEEKDAYS`` - Monday through Friday.
    * ``WEEKLY``   - only on ``recur_day`` (no day set means never due).
    """
    if recurs == Recurrence.DAILY:
        return True
    if recurs == Recurrence.WEEKDAYS:
        return day.weekday() < 5  # Mon=0 .. Fri=4
    if recurs == Recurrence.WEEKLY:
        return recur_day is not None and day.weekday() == recur_day.weekday_index
    return False


def _eligible_tasks(day: date, task_source: TaskSource) -> list[Task]:
    """Today's candidate tasks to feed the planner.

    A one-shot task is eligible while not ``DONE`` and either has no
    ``planned_date`` (unchanged backlog-until-done behavior) or its
    ``planned_date`` matches ``day`` exactly. A recurring task is a candidate
    only on its due day; if it is due today but was completed on a prior day,
    it is reset to ``BACKLOG`` so it re-enters today's plan and then flows
    through the normal flexible placement.

    Assumes at most one planning run per day (the morning trigger): a recurring
    task completed *and* re-planned within the same day would be reset again.
    """
    eligible: list[Task] = []
    for t in task_source.list_tasks():
        if t.recurs is None:
            is_planned_for_today = t.planned_date is None or t.planned_date == day
            if t.status != Status.DONE and is_planned_for_today:
                eligible.append(t)
            continue
        # Recurring: a candidate only on its due day.
        if not is_due(t.recurs, t.recur_day, day):
            continue
        if t.status == Status.DONE:
            # Completed on a prior due day; bring it back for today.
            t = task_source.update_task(t.id, status=Status.BACKLOG)
        eligible.append(t)
    return eligible


def _bump_for_interview_proximity(
    tasks: list[Task], interview_source: InterviewSource, day: date
) -> list[Task]:
    """Return a copy of ``tasks`` with priority bumped one level (floor P0) for
    any task linked to an interview happening within
    :data:`INTERVIEW_PROXIMITY_DAYS` of ``day``.

    Never mutates the input tasks or persists the bump - it's a same-run
    scheduling nudge only, so the boost disappears once the interview passes
    without leaving a stale, artificially-elevated priority behind.
    """
    day_start = datetime.combine(day, time.min)
    upcoming: dict[str, Interview] = {
        i.id: i for i in interview_source.list_upcoming(after=day_start)
    }
    bumped: list[Task] = []
    for t in tasks:
        interview = upcoming.get(t.interview_id) if t.interview_id else None
        if interview and (interview.scheduled_at.date() - day).days <= INTERVIEW_PROXIMITY_DAYS:
            new_priority = Priority(max(0, t.priority.value - 1))
            bumped.append(dataclasses.replace(t, priority=new_priority))
        else:
            bumped.append(t)
    return bumped


def _compute_free(
    day: date, busy: list[TimeSlot], day_start_hour: int, day_end_hour: int
) -> list[TimeSlot]:
    """Free intervals inside the planning-day window, with busy time removed."""
    window_start = datetime.combine(day, time(hour=day_start_hour))
    window_end = datetime.combine(day, time(hour=day_end_hour))
    free = [TimeSlot(window_start, window_end)]
    for slot in busy:
        free = _subtract(free, slot)
    return free


def _subtract(intervals: list[TimeSlot], span: TimeSlot) -> list[TimeSlot]:
    """Remove ``span`` from each interval, keeping the surrounding remainders."""
    result: list[TimeSlot] = []
    for iv in intervals:
        if not iv.overlaps(span):
            result.append(iv)
            continue
        if iv.start < span.start:
            result.append(TimeSlot(iv.start, span.start))
        if span.end < iv.end:
            result.append(TimeSlot(span.end, iv.end))
    return result


def _sample_setup() -> tuple[date, TaskSource, CalendarClient]:
    """A realistic no-credentials scenario for the console entrypoint: a fixed
    Leetcode contest, several prep tasks, and an errand, plus one pre-existing
    calendar event the planner must respect."""
    from dayline.adapters.calendar import CalendarEvent, InMemoryCalendar
    from dayline.adapters.task_source import InMemoryTaskSource
    from dayline.models import Category, Priority, Task, Window

    day = date(2026, 8, 31)

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour=hour, minute=minute))

    tasks = [
        Task("Leetcode weekly contest", Category.LEETCODE, Priority.P0, 90, "t-contest",
             fixed_time=at(10, 30)),
        Task("Behavioral story polish", Category.BEHAVIORAL, Priority.P1, 60, "t-behav",
             preferred_window=Window.MORNING),
        Task("System design: rate limiter", Category.SYSTEM_DESIGN, Priority.P1, 90,
             "t-sysd", preferred_window=Window.AFTERNOON),
        Task("AI coding practice", Category.AI_CODING_REACT_PYTHON, Priority.P2, 60, "t-aicode"),
        Task("Pick up dry cleaning", Category.ERRAND, Priority.P2, 30, "t-errand"),
        Task("Read a paper", Category.OTHER, Priority.P3, 45, "t-paper"),
    ]
    task_source = InMemoryTaskSource(tasks)

    calendar = InMemoryCalendar(
        [CalendarEvent("pre-standup", "Team standup", at(9, 0), at(9, 30))]
    )
    return day, task_source, calendar


def main() -> None:
    """Console entrypoint. Runs the pipeline against the in-memory fakes and
    prints the brief - a stand-in for the future morning cron trigger."""
    day, task_source, calendar = _sample_setup()
    plan = run_daily_plan(day, task_source, calendar)
    print(plan.brief)


if __name__ == "__main__":
    main()
