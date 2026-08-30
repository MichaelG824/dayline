"""Unit tests for the planning core - one test per rule in the brief."""

from __future__ import annotations

from day_planner.models import Category, Priority, ScheduledBlock, TimeSlot, Window
from day_planner.planner.core import build_plan
from tests.fixtures import DAY, at, slot, task


def _no_overlaps(blocks: list[ScheduledBlock]) -> bool:
    ordered = sorted(blocks, key=lambda b: b.start)
    return all(a.end <= b.start for a, b in zip(ordered, ordered[1:], strict=False))


def _within_free(blocks: list[ScheduledBlock], free: list[TimeSlot]) -> bool:
    return all(any(f.contains(b.slot) for f in free) for b in blocks)


# --- Rule 1: fixed-time anchoring ----------------------------------------- #
def test_fixed_time_task_is_anchored_at_its_time() -> None:
    contest = task(
        "contest", category=Category.LEETCODE, priority=Priority.P0, duration=90,
        fixed_time=at(10, 30),
    )
    plan = build_plan([contest], [slot(8, 22)], DAY)

    assert len(plan.blocks) == 1
    block = plan.blocks[0]
    assert block.task_id == "contest"
    assert block.start == at(10, 30)
    assert block.end == at(12, 0)
    assert not plan.unplaced


def test_fixed_time_over_busy_is_reported_not_overlapped() -> None:
    # Free time is 8-9 and 11-22 (busy 9-11). A fixed task at 10:00 collides.
    free = [slot(8, 9), slot(11, 22)]
    fixed = task("call", priority=Priority.P0, duration=60, fixed_time=at(10, 0))

    plan = build_plan([fixed], free, DAY)

    assert not plan.blocks
    assert [t.id for t in plan.unplaced] == ["call"]
    assert "fixed time" in plan.brief


def test_two_fixed_tasks_that_collide_report_conflict_not_overlap() -> None:
    a = task("a", priority=Priority.P0, duration=90, fixed_time=at(10, 0))
    b = task("b", priority=Priority.P0, duration=90, fixed_time=at(11, 0))  # overlaps a

    plan = build_plan([a, b], [slot(8, 22)], DAY)

    assert [blk.task_id for blk in plan.blocks] == ["a"]
    assert [t.id for t in plan.unplaced] == ["b"]
    assert _no_overlaps(plan.blocks)


# --- Rule 3/4: zero collisions with pre-existing busy events --------------- #
def test_no_collisions_with_busy_or_between_blocks() -> None:
    # Busy 10-12 => free is 8-10 and 12-14. Several tasks must pack without ever
    # touching the busy gap or each other.
    free = [slot(8, 10), slot(12, 14)]
    tasks = [
        task("p1", category=Category.SYSTEM_DESIGN, priority=Priority.P0, duration=60),
        task("p2", category=Category.AI_CODING, priority=Priority.P1, duration=60),
        task("p3", category=Category.BEHAVIORAL, priority=Priority.P1, duration=60),
    ]
    plan = build_plan(tasks, free, DAY)

    busy = TimeSlot(at(10), at(12))
    assert all(not b.slot.overlaps(busy) for b in plan.blocks)
    assert _no_overlaps(plan.blocks)
    assert _within_free(plan.blocks, free)


# --- Rule 2 tie-break: prep beats errand on equal priority ---------------- #
def test_prep_outranks_errand_on_priority_tie_when_capacity_scarce() -> None:
    # One 60-min slot, two equal-priority 60-min tasks. Prep must win the slot.
    prep = task("prep", category=Category.AI_CODING, priority=Priority.P2, duration=60)
    errand = task("errand", category=Category.ERRAND, priority=Priority.P2, duration=60)

    plan = build_plan([errand, prep], [slot(8, 9)], DAY)

    assert [b.task_id for b in plan.blocks] == ["prep"]
    assert [t.id for t in plan.unplaced] == ["errand"]


def test_prep_scheduled_before_errand_when_both_fit() -> None:
    prep = task("prep", category=Category.SYSTEM_DESIGN, priority=Priority.P2, duration=60)
    errand = task("errand", category=Category.ERRAND, priority=Priority.P2, duration=60)

    plan = build_plan([errand, prep], [slot(8, 10)], DAY)

    ordered = [b.task_id for b in plan.blocks]
    assert ordered == ["prep", "errand"]
    assert not plan.unplaced


# --- Rule 2: priority ordering -------------------------------------------- #
def test_higher_priority_wins_scarce_slot() -> None:
    p0 = task("p0", category=Category.OTHER, priority=Priority.P0, duration=60)
    p3 = task("p3", category=Category.OTHER, priority=Priority.P3, duration=60)

    plan = build_plan([p3, p0], [slot(8, 9)], DAY)

    assert [b.task_id for b in plan.blocks] == ["p0"]
    assert [t.id for t in plan.unplaced] == ["p3"]


# --- Rule 2: preferred window --------------------------------------------- #
def test_preferred_window_respected_when_feasible() -> None:
    # A big morning-through-evening gap; an afternoon-preferring task must land
    # at/after noon even though left-packing would otherwise start it at 08:00.
    afternoon = task(
        "sysd", category=Category.SYSTEM_DESIGN, priority=Priority.P1, duration=60,
        preferred_window=Window.AFTERNOON,
    )
    plan = build_plan([afternoon], [slot(8, 18)], DAY)

    assert len(plan.blocks) == 1
    assert plan.blocks[0].start >= at(12, 0)
    assert plan.blocks[0].start < at(17, 0)


def test_preferred_window_ignored_when_infeasible_but_task_still_placed() -> None:
    # Prefers evening, but only a morning gap exists; it must still be placed.
    evening = task(
        "read", category=Category.OTHER, priority=Priority.P2, duration=60,
        preferred_window=Window.EVENING,
    )
    plan = build_plan([evening], [slot(8, 11)], DAY)

    assert len(plan.blocks) == 1
    assert plan.blocks[0].start == at(8, 0)


# --- Rule 4: unplaceable tasks reported ----------------------------------- #
def test_unplaceable_task_is_reported_not_dropped() -> None:
    big = task("big", priority=Priority.P0, duration=120)
    plan = build_plan([big], [slot(8, 9)], DAY)  # only 60 min free

    assert not plan.blocks
    assert [t.id for t in plan.unplaced] == ["big"]
    assert "big" in plan.brief and "Unplaced" in plan.brief


# --- Determinism ---------------------------------------------------------- #
def test_build_plan_is_deterministic_regardless_of_input_order() -> None:
    tasks = [
        task("contest", category=Category.LEETCODE, priority=Priority.P0, duration=90,
             fixed_time=at(10, 30)),
        task("behav", category=Category.BEHAVIORAL, priority=Priority.P1, duration=60,
             preferred_window=Window.MORNING),
        task("errand", category=Category.ERRAND, priority=Priority.P2, duration=30),
        task("aicode", category=Category.AI_CODING, priority=Priority.P1, duration=60),
    ]
    free = [slot(8, 18)]

    plan_a = build_plan(tasks, free, DAY)
    plan_b = build_plan(list(reversed(tasks)), free, DAY)

    assert [(b.task_id, b.start) for b in plan_a.blocks] == [
        (b.task_id, b.start) for b in plan_b.blocks
    ]
    assert plan_a.brief == plan_b.brief
