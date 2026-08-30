"""The planning core (Subtask 4).

``build_plan`` is a **pure, deterministic** function with zero I/O: it takes the
open tasks, the day's free time slots, and the date, and returns a collision-free
time-blocked :class:`~day_planner.models.Plan`. Because it never touches the
network it is trivially unit-testable on fixtures, and every trigger (cron,
Streamlit, a future chat surface) shares this one implementation.

Scheduling rules, applied in order:

1. **Anchor fixed-time tasks.** Each ``fixed_time`` task is pinned at its time.
   It must fit entirely inside free time (never overlapping a pre-existing busy
   event) and must not overlap another anchored task. A task that cannot be
   placed without a collision is reported as *unplaced* rather than overlapped.
2. **Pack the rest by priority.** Remaining tasks are ordered by priority
   (P0 first), with job-search *prep* categories outranking ``ERRAND``/``OTHER``
   on ties. Each task is placed into a free slot, honoring its
   ``preferred_window`` when a fitting slot exists there, and otherwise choosing
   the best-fitting slot (tightest gap that still holds the task).
3. **Never collide.** Placed blocks never overlap busy events or each other.
4. **Report, don't drop.** Tasks that cannot be placed are returned in
   ``unplaced`` with a reason in the brief.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from day_planner.models import (
    WINDOW_HOURS,
    Plan,
    ScheduledBlock,
    Task,
    TimeSlot,
    Window,
)


def build_plan(tasks: Iterable[Task], free_slots: Iterable[TimeSlot], day: date) -> Plan:
    """Compute a deterministic, collision-free time-blocked plan for ``day``.

    Args:
        tasks: Open tasks to schedule. Order does not affect the result.
        free_slots: The day's free intervals (the complement of busy events).
        day: The calendar date being planned; used for window anchoring and the
            brief.

    Returns:
        A :class:`Plan` with ordered ``blocks``, any ``unplaced`` tasks, and a
        short human-readable ``brief``.
    """
    task_list = list(tasks)
    free = _normalize(free_slots)

    unplaced: list[Task] = []
    reasons: dict[str, str] = {}

    fixed = sorted(
        (t for t in task_list if t.fixed_time is not None),
        key=lambda t: (t.fixed_time, t.id),
    )
    flexible = [t for t in task_list if t.fixed_time is None]

    # --- Rule 1: anchor fixed-time tasks -------------------------------------
    anchored: list[ScheduledBlock] = []
    for t in fixed:
        assert t.fixed_time is not None  # narrowed by construction
        span = TimeSlot(t.fixed_time, t.fixed_time + timedelta(minutes=t.est_duration_min))
        fits_free = any(slot.contains(span) for slot in free)
        hits_anchor = any(span.overlaps(b.slot) for b in anchored)
        if fits_free and not hits_anchor:
            anchored.append(ScheduledBlock(t.id, span.start, span.end, t.name))
        else:
            unplaced.append(t)
            reasons[t.id] = (
                "fixed time overlaps another anchored task"
                if hits_anchor
                else "fixed time overlaps a busy event or falls outside free time"
            )

    # Remaining capacity = free time minus what we just anchored.
    available = free
    for b in anchored:
        available = _subtract(available, b.slot)

    # --- Rule 2: pack remaining tasks by priority, prep-before-errand --------
    flexible.sort(key=_pack_order)
    packed: list[ScheduledBlock] = []
    for t in flexible:
        start = _choose_start(available, t, day)
        if start is None:
            unplaced.append(t)
            reasons[t.id] = f"no free slot fits {t.est_duration_min} min"
            continue
        block = ScheduledBlock(
            t.id, start, start + timedelta(minutes=t.est_duration_min), t.name
        )
        packed.append(block)
        available = _subtract(available, block.slot)

    blocks = sorted(anchored + packed, key=lambda b: (b.start, b.task_id))
    brief = _build_brief(day, blocks, unplaced, task_list, reasons)
    return Plan(blocks=blocks, unplaced=unplaced, brief=brief)


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #
def _pack_order(task: Task) -> tuple[int, int, str, str]:
    """Sort key for flexible tasks: priority first (P0 == 0), then prep
    categories ahead of errands/other on ties, then a stable name/id tiebreak so
    the result is fully deterministic."""
    return (
        task.priority.value,
        0 if task.category.is_prep else 1,
        task.name,
        task.id,
    )


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
def _choose_start(available: list[TimeSlot], task: Task, day: date) -> datetime | None:
    """Pick the start time for ``task`` among the currently ``available`` gaps.

    Preference order:
      1. If the task has a ``preferred_window`` and any gap can hold it *inside*
         that window, only those placements are considered.
      2. Among the considered gaps, the tightest fit wins (smallest gap that
         still holds the task), so long tasks don't fragment large gaps
         unnecessarily. Ties break on earliest start for determinism.
    """
    duration = timedelta(minutes=task.est_duration_min)

    windowed: list[tuple[TimeSlot, datetime]] = []
    plain: list[tuple[TimeSlot, datetime]] = []
    for gap in available:
        if gap.duration_min < task.est_duration_min:
            continue
        plain.append((gap, gap.start))
        if task.preferred_window is not None:
            pos = _window_start(gap, duration, task.preferred_window, day)
            if pos is not None:
                windowed.append((gap, pos))

    candidates = windowed if (task.preferred_window is not None and windowed) else plain
    if not candidates:
        return None

    gap, start = min(candidates, key=lambda c: (c[0].duration_min, c[1], c[0].start))
    return start


def _window_start(
    gap: TimeSlot, duration: timedelta, window: Window, day: date
) -> datetime | None:
    """Earliest start within ``gap`` that both begins inside ``window`` and
    leaves room for ``duration``; ``None`` if the window can't hold it."""
    lo_hour, hi_hour = WINDOW_HOURS[window]
    win_start = datetime.combine(day, time(hour=lo_hour))
    win_end = (
        datetime.combine(day, time(hour=0)) + timedelta(days=1)
        if hi_hour == 24
        else datetime.combine(day, time(hour=hi_hour))
    )

    start = max(gap.start, win_start)
    if start >= win_end:
        return None
    if start + duration > gap.end:
        return None
    return start


# --------------------------------------------------------------------------- #
# Interval math
# --------------------------------------------------------------------------- #
def _normalize(slots: Iterable[TimeSlot]) -> list[TimeSlot]:
    """Sort free slots by start and merge any that touch or overlap, so the
    packer sees clean, maximal, non-overlapping gaps."""
    ordered = sorted(slots, key=lambda s: s.start)
    merged: list[TimeSlot] = []
    for slot in ordered:
        if merged and slot.start <= merged[-1].end:
            last = merged[-1]
            if slot.end > last.end:
                merged[-1] = TimeSlot(last.start, slot.end)
        else:
            merged.append(slot)
    return merged


def _subtract(intervals: list[TimeSlot], span: TimeSlot) -> list[TimeSlot]:
    """Remove ``span`` from each interval, keeping the surrounding remainders.

    ``intervals`` stays sorted and non-overlapping.
    """
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


# --------------------------------------------------------------------------- #
# Brief
# --------------------------------------------------------------------------- #
def _build_brief(
    day: date,
    blocks: list[ScheduledBlock],
    unplaced: list[Task],
    tasks: list[Task],
    reasons: dict[str, str],
) -> str:
    """Render the ordered blocks and anything that didn't fit as a short,
    scannable brief."""
    by_id = {t.id: t for t in tasks}
    lines = [f"Plan for {day.isoformat()}"]

    if blocks:
        for b in blocks:
            t = by_id.get(b.task_id)
            meta = f" ({t.category.value}, {t.priority.name})" if t else ""
            lines.append(
                f"  {_fmt(b.start)}-{_fmt(b.end)}  {b.title}{meta}"
            )
    else:
        lines.append("  (nothing scheduled)")

    if unplaced:
        lines.append(f"Unplaced ({len(unplaced)}):")
        for t in unplaced:
            why = reasons.get(t.id, "could not be placed")
            lines.append(f"  - {t.name} ({t.category.value}, {t.priority.name}) - {why}")

    return "\n".join(lines)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")
