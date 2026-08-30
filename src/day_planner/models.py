"""Typed domain models for the planner.

Deliberately stdlib-only (``dataclasses`` + ``enum``) so the core and adapter
interfaces stay dependency-free and trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, StrEnum


class Category(StrEnum):
    """Task category. The first four are job-search *prep* categories and, per
    the planning rules, outrank ``ERRAND``/``OTHER`` when priorities tie."""

    BEHAVIORAL = "Behavioral"
    AI_CODING = "AI Coding"
    LEETCODE = "Leetcode"
    SYSTEM_DESIGN = "System Design"
    ERRAND = "Errand"
    OTHER = "Other"

    @property
    def is_prep(self) -> bool:
        """True for job-search prep categories (behavioral, AI coding, leetcode,
        system design)."""
        return self in _PREP_CATEGORIES


_PREP_CATEGORIES = frozenset(
    {
        Category.BEHAVIORAL,
        Category.AI_CODING,
        Category.LEETCODE,
        Category.SYSTEM_DESIGN,
    }
)


class Priority(Enum):
    """Task priority. ``P0`` is the most important; lower enum value == higher
    priority, which keeps ordering comparisons obvious."""

    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


class Status(StrEnum):
    """Lifecycle of a task."""

    BACKLOG = "Backlog"
    SCHEDULED = "Scheduled"
    DONE = "Done"


class Window(StrEnum):
    """A coarse time-of-day preference for a task."""

    MORNING = "Morning"
    AFTERNOON = "Afternoon"
    EVENING = "Evening"


# Half-open hour boundaries [start, end) used to test whether a datetime falls
# inside a preferred window. Evening runs to 24 so late blocks still qualify.
WINDOW_HOURS: dict[Window, tuple[int, int]] = {
    Window.MORNING: (5, 12),
    Window.AFTERNOON: (12, 17),
    Window.EVENING: (17, 24),
}


@dataclass(slots=True)
class Task:
    """A unit of work to be scheduled."""

    name: str
    category: Category
    priority: Priority
    est_duration_min: int
    id: str
    status: Status = Status.BACKLOG
    fixed_time: datetime | None = None
    preferred_window: Window | None = None
    due_date: datetime | None = None

    def __post_init__(self) -> None:
        if self.est_duration_min <= 0:
            raise ValueError(
                f"est_duration_min must be positive, got {self.est_duration_min!r}"
            )


@dataclass(slots=True, frozen=True)
class TimeSlot:
    """A half-open interval ``[start, end)``. Used for both busy events and the
    free gaps between them."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"TimeSlot end {self.end} must be after start {self.start}")

    @property
    def duration_min(self) -> int:
        """Length of the slot in whole minutes."""
        return int((self.end - self.start).total_seconds() // 60)

    def overlaps(self, other: TimeSlot) -> bool:
        """True when this slot and ``other`` share any interior time.

        Half-open semantics: touching endpoints (one ends exactly when the other
        starts) do *not* count as an overlap.
        """
        return self.start < other.end and other.start < self.end

    def contains(self, other: TimeSlot) -> bool:
        """True when ``other`` fits entirely within this slot."""
        return self.start <= other.start and other.end <= self.end


@dataclass(slots=True, frozen=True)
class ScheduledBlock:
    """A task placed on the timeline. ``title`` carries the display label used
    when the scheduler writes the block to a calendar."""

    task_id: str
    start: datetime
    end: datetime
    title: str

    @property
    def slot(self) -> TimeSlot:
        return TimeSlot(self.start, self.end)


@dataclass(slots=True)
class Plan:
    """Output of the planning core: placed blocks, everything that did not fit,
    and a short human-readable brief."""

    blocks: list[ScheduledBlock] = field(default_factory=list)
    unplaced: list[Task] = field(default_factory=list)
    brief: str = ""
