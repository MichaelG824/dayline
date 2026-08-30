"""End-to-end tests for the scheduler against the in-memory fakes.

Proves the full pull -> plan -> write-back loop produces a correct plan and is
idempotent (running twice yields no duplicate blocks and the same result).
"""

from __future__ import annotations

from day_planner.adapters.calendar import CalendarEvent, InMemoryCalendar
from day_planner.adapters.task_source import InMemoryTaskSource
from day_planner.models import Category, Priority, Status
from day_planner.scheduler.run import AGENT_MARKER, run_daily_plan
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
