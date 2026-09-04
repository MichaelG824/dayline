"""End-to-end tests for the scheduler against the in-memory fakes.

Proves the full pull -> plan -> write-back loop produces a correct plan and is
idempotent (running twice yields no duplicate blocks and the same result).
"""

from __future__ import annotations

from datetime import timedelta

from dayline.adapters.calendar import CalendarEvent, InMemoryCalendar
from dayline.adapters.interview_source import InMemoryInterviewSource
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.models import Category, Interview, InterviewCategory, Priority, Status
from dayline.scheduler.run import AGENT_MARKER, run_daily_plan, sync_plan_to_calendar
from tests.fixtures import DAY, at, task


def _scenario() -> tuple[InMemoryTaskSource, InMemoryCalendar]:
    tasks = [
        task("contest", category=Category.LEETCODE, priority=Priority.P0, duration=90,
             fixed_time=at(10, 30)),
        task("behav", category=Category.BEHAVIORAL, priority=Priority.P1, duration=60),
        task("sysd", category=Category.SYSTEM_DESIGN, priority=Priority.P1, duration=60),
        task("errand", category=Category.ERRAND, priority=Priority.P2, duration=30),
    ]
    source = InMemoryTaskSource(tasks)
    # A pre-existing event the planner must respect (never overlap).
    calendar = InMemoryCalendar(
        [CalendarEvent("standup", "Team standup", at(9, 0), at(9, 30))]
    )
    return source, calendar


def _agent_blocks(calendar: InMemoryCalendar) -> list[CalendarEvent]:
    return [e for e in calendar.list_events(DAY) if e.title.startswith(AGENT_MARKER)]


def test_run_produces_correct_plan_and_writes_back() -> None:
    source, calendar = _scenario()
    plan = run_daily_plan(DAY, source, calendar)

    # Fixed contest anchored at its time.
    contest = next(b for b in plan.blocks if b.task_id == "contest")
    assert contest.start == at(10, 30)

    # Never overlaps the pre-existing standup (09:00-09:30).
    standup = CalendarEvent("standup", "Team standup", at(9, 0), at(9, 30)).slot
    assert all(not b.slot.overlaps(standup) for b in plan.blocks)

    # Every planned task flipped to SCHEDULED with a recorded time in the source.
    for b in plan.blocks:
        assert source.get_task(b.task_id).status == Status.SCHEDULED
        assert source.scheduled_time_of(b.task_id) == b.start

    # Calendar got one marker-tagged block per planned block.
    assert len(_agent_blocks(calendar)) == len(plan.blocks)


def test_run_is_idempotent_no_duplicates_same_result() -> None:
    source, calendar = _scenario()

    first = run_daily_plan(DAY, source, calendar)
    blocks_after_first = len(_agent_blocks(calendar))

    second = run_daily_plan(DAY, source, calendar)
    blocks_after_second = len(_agent_blocks(calendar))

    # Re-running reconciles rather than duplicating.
    assert blocks_after_second == blocks_after_first
    assert blocks_after_second == len(second.blocks)

    # Identical plan the second time around.
    assert [(b.task_id, b.start, b.end) for b in first.blocks] == [
        (b.task_id, b.start, b.end) for b in second.blocks
    ]
    assert first.brief == second.brief


def test_run_never_overlaps_preexisting_and_leaves_it_intact() -> None:
    source, calendar = _scenario()
    run_daily_plan(DAY, source, calendar)

    # The pre-existing event is untouched (not deleted by reconciliation).
    titles = [e.title for e in calendar.list_events(DAY)]
    assert "Team standup" in titles


def test_prep_placed_before_errand_end_to_end() -> None:
    source, calendar = _scenario()
    plan = run_daily_plan(DAY, source, calendar)

    order = [b.task_id for b in plan.blocks]
    # Errand (P2) comes after the P1 prep tasks in the timeline.
    assert order.index("errand") > order.index("behav")
    assert order.index("errand") > order.index("sysd")


def test_planned_date_filters_one_shot_tasks_to_their_day() -> None:
    tomorrow = DAY + timedelta(days=1)
    source = InMemoryTaskSource(
        [task("today-only", planned_date=DAY), task("tomorrow-only", planned_date=tomorrow)]
    )
    calendar = InMemoryCalendar()

    today_plan = run_daily_plan(DAY, source, calendar)
    assert {b.task_id for b in today_plan.blocks} == {"today-only"}

    tomorrow_plan = run_daily_plan(tomorrow, source, calendar)
    assert {b.task_id for b in tomorrow_plan.blocks} == {"tomorrow-only"}


def test_planned_date_none_is_eligible_every_day() -> None:
    source = InMemoryTaskSource([task("anytime", planned_date=None)])
    calendar = InMemoryCalendar()

    plan = run_daily_plan(DAY, source, calendar)
    assert {b.task_id for b in plan.blocks} == {"anytime"}


def test_interview_proximity_bumps_priority_to_win_scarce_slot() -> None:
    # Only one 60-minute gap exists (21:00-22:00); two same-priority, same-
    # duration prep tasks compete for it. Without any bump, the tightest-fit
    # tiebreak falls back to name order ("far" < "near"), so "far" would win.
    # Linking "near" to an interview 2 days out should bump it to P1 and let
    # it win the slot instead.
    source = InMemoryTaskSource(
        [
            task("near", name="near", category=Category.BEHAVIORAL, priority=Priority.P2,
                 duration=60, interview_id="int-1"),
            task("far", name="far", category=Category.BEHAVIORAL, priority=Priority.P2,
                 duration=60),
        ]
    )
    calendar = InMemoryCalendar(
        [CalendarEvent("busy", "Busy all day", at(8, 0), at(21, 0))]
    )
    interviews = InMemoryInterviewSource(
        [
            Interview(
                id="int-1",
                application_id="app-1",
                category=InterviewCategory.BEHAVIORAL,
                scheduled_at=at(10, 0, day=DAY + timedelta(days=2)),
            )
        ]
    )

    plan = run_daily_plan(DAY, source, calendar, interview_source=interviews)

    assert [b.task_id for b in plan.blocks] == ["near"]
    assert plan.unplaced and plan.unplaced[0].id == "far"


def test_sync_plan_to_calendar_pushes_marker_blocks_to_a_second_calendar() -> None:
    # Plan against the normal in-memory calendar, then mirror the result to a
    # separate "real" calendar - the standalone push api/main.py uses for
    # Google Calendar, independent of what run_daily_plan itself planned
    # against.
    source, calendar = _scenario()
    plan = run_daily_plan(DAY, source, calendar)

    real_calendar = InMemoryCalendar()
    sync_plan_to_calendar(real_calendar, DAY, plan)

    assert len(_agent_blocks(real_calendar)) == len(plan.blocks)


def test_sync_plan_to_calendar_is_idempotent() -> None:
    source, calendar = _scenario()
    plan = run_daily_plan(DAY, source, calendar)
    real_calendar = InMemoryCalendar()

    sync_plan_to_calendar(real_calendar, DAY, plan)
    first_count = len(_agent_blocks(real_calendar))
    sync_plan_to_calendar(real_calendar, DAY, plan)
    second_count = len(_agent_blocks(real_calendar))

    assert second_count == first_count == len(plan.blocks)


def test_sync_plan_to_calendar_leaves_non_marker_events_alone() -> None:
    source, calendar = _scenario()
    plan = run_daily_plan(DAY, source, calendar)
    real_calendar = InMemoryCalendar(
        [CalendarEvent("recruiter-call", "Recruiter call", at(13, 0), at(13, 30))]
    )

    sync_plan_to_calendar(real_calendar, DAY, plan)

    titles = [e.title for e in real_calendar.list_events(DAY)]
    assert "Recruiter call" in titles


def test_no_interview_source_means_no_priority_bump() -> None:
    # Same scenario as above, but without passing interview_source: "far"
    # wins the scarce slot via plain name-order tiebreak, proving the bump is
    # opt-in and existing callers are unaffected.
    source = InMemoryTaskSource(
        [
            task("near", name="near", category=Category.BEHAVIORAL, priority=Priority.P2,
                 duration=60, interview_id="int-1"),
            task("far", name="far", category=Category.BEHAVIORAL, priority=Priority.P2,
                 duration=60),
        ]
    )
    calendar = InMemoryCalendar(
        [CalendarEvent("busy", "Busy all day", at(8, 0), at(21, 0))]
    )

    plan = run_daily_plan(DAY, source, calendar)

    assert [b.task_id for b in plan.blocks] == ["far"]
