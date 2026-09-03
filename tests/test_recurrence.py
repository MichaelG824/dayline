"""Tests for recurring-task scheduling (daily / weekdays / weekly).

Recurrence is an eligibility layer in the scheduler, *before* the pure planner:
a recurring task is a candidate only on its due day, and one completed on a
prior day is reset so it re-enters today's plan.

Calendar reference: ``2026-08-31`` is a Monday, so the dates below are:
    MON 08-31, FRI 09-04, SAT 09-05, SUN 09-06.
"""

from __future__ import annotations

from datetime import date

from dayline.adapters.calendar import InMemoryCalendar
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.models import Recurrence, Status, Weekday
from dayline.scheduler.run import is_due, run_daily_plan
from tests.fixtures import task

MON = date(2026, 8, 31)
FRI = date(2026, 9, 4)
SAT = date(2026, 9, 5)
SUN = date(2026, 9, 6)


def _planned(source, calendar, day, task_id) -> bool:
    plan = run_daily_plan(day, source, calendar)
    return any(b.task_id == task_id for b in plan.blocks)


# --- is_due (pure) -----------------------------------------------------------
def test_is_due_daily_every_day() -> None:
    for d in (MON, FRI, SAT, SUN):
        assert is_due(Recurrence.DAILY, None, d)


def test_is_due_weekdays_skips_weekend() -> None:
    assert is_due(Recurrence.WEEKDAYS, None, MON)
    assert is_due(Recurrence.WEEKDAYS, None, FRI)
    assert not is_due(Recurrence.WEEKDAYS, None, SAT)
    assert not is_due(Recurrence.WEEKDAYS, None, SUN)


def test_is_due_weekly_only_on_its_day() -> None:
    assert is_due(Recurrence.WEEKLY, Weekday.SUN, SUN)
    assert not is_due(Recurrence.WEEKLY, Weekday.SUN, MON)
    assert not is_due(Recurrence.WEEKLY, Weekday.SUN, SAT)


def test_is_due_weekly_without_a_day_is_never_due() -> None:
    assert not is_due(Recurrence.WEEKLY, None, SUN)


# --- end-to-end scheduler behavior -------------------------------------------
def test_daily_recurring_completed_yesterday_is_reset_and_planned() -> None:
    source = InMemoryTaskSource([task("study", duration=60, recurs=Recurrence.DAILY)])
    # Simulate it having been completed on a prior day.
    source.update_task("study", status=Status.DONE)

    plan = run_daily_plan(MON, source, InMemoryCalendar())

    assert any(b.task_id == "study" for b in plan.blocks)
    # Planning flips it to SCHEDULED again for today.
    assert source.get_task("study").status == Status.SCHEDULED


def test_weekly_task_planned_only_on_its_day() -> None:
    def fresh() -> InMemoryTaskSource:
        return InMemoryTaskSource(
            [task("sysd", duration=60, recurs=Recurrence.WEEKLY, recur_day=Weekday.SUN)]
        )

    assert not _planned(fresh(), InMemoryCalendar(), MON, "sysd")
    assert _planned(fresh(), InMemoryCalendar(), SUN, "sysd")


def test_weekdays_task_skips_the_weekend() -> None:
    def fresh() -> InMemoryTaskSource:
        return InMemoryTaskSource([task("leet", duration=60, recurs=Recurrence.WEEKDAYS)])

    assert _planned(fresh(), InMemoryCalendar(), FRI, "leet")
    assert not _planned(fresh(), InMemoryCalendar(), SAT, "leet")


def test_recurring_same_day_rerun_is_idempotent() -> None:
    source = InMemoryTaskSource([task("study", duration=60, recurs=Recurrence.DAILY)])
    calendar = InMemoryCalendar()

    first = run_daily_plan(MON, source, calendar)
    second = run_daily_plan(MON, source, calendar)

    assert [(b.task_id, b.start, b.end) for b in first.blocks] == [
        (b.task_id, b.start, b.end) for b in second.blocks
    ]
    assert first.brief == second.brief
