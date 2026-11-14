"""Typed domain models for the planner.

Deliberately stdlib-only (``dataclasses`` + ``enum``) so the core and adapter
interfaces stay dependency-free and trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, StrEnum


class Category(StrEnum):
    """Task category. The first five are job-search *prep* categories and, per
    the planning rules, outrank ``ERRAND``/``OTHER`` when priorities tie.

    ``AI_CODING_REACT_PYTHON``/``AI_CODING_DSA`` (AI-assisted practice) and
    ``LEETCODE`` (pure DSA, no AI assistance) are deliberately distinct
    categories, not degrees of one "AI coding" bucket: the user's focus shifts
    between them independently, so each carries its own default priority (see
    ``adapters/category_weights.py``)."""

    AI_CODING_REACT_PYTHON = "AI Coding - React/Python"
    AI_CODING_DSA = "AI Coding - DSA"
    BEHAVIORAL = "Behavioral"
    SYSTEM_DESIGN = "System Design"
    LEETCODE = "Leetcode"
    ERRAND = "Errand"
    OTHER = "Other"

    @property
    def is_prep(self) -> bool:
        """True for job-search prep categories (the two AI-coding variants,
        behavioral, system design, leetcode)."""
        return self in _PREP_CATEGORIES


_PREP_CATEGORIES = frozenset(
    {
        Category.AI_CODING_REACT_PYTHON,
        Category.AI_CODING_DSA,
        Category.BEHAVIORAL,
        Category.SYSTEM_DESIGN,
        Category.LEETCODE,
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


class ApplicationStage(StrEnum):
    """Stage of a job application in the funnel. Ordered roughly by how far
    along the process is; ``REJECTED`` can follow any stage."""

    APPLIED = "Applied"
    PHONE_SCREEN = "Phone Screen"
    TECHNICAL = "Technical"
    ONSITE = "Onsite"
    OFFER = "Offer"
    REJECTED = "Rejected"


class InterviewCategory(StrEnum):
    """Which of the 5 ranked prep categories an interview round is. Kept as
    its own enum (not reusing :class:`Category`) so ``ERRAND``/``OTHER`` can
    never be selected as an interview type - only the 5 prep categories are
    valid interview rounds."""

    AI_CODING_REACT_PYTHON = "AI Coding - React/Python"
    AI_CODING_DSA = "AI Coding - DSA"
    BEHAVIORAL = "Behavioral"
    SYSTEM_DESIGN = "System Design"
    LEETCODE = "Leetcode"


class Difficulty(StrEnum):
    """LeetCode difficulty of a :class:`Problem`."""

    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


class ProblemStatus(StrEnum):
    """Where a :class:`Problem` stands in practice. Distinct from task
    :class:`Status`: a problem outlives any one scheduled practice session."""

    TODO = "To do"
    ATTEMPTED = "Attempted"
    SOLVED = "Solved"
    REVIEW = "Review"


class Recurrence(StrEnum):
    """How a task repeats. ``None`` on a task means one-shot (the default)."""

    DAILY = "Daily"
    WEEKDAYS = "Weekdays"
    WEEKLY = "Weekly"


class Weekday(StrEnum):
    """A day of the week. ``weekday_index`` matches :meth:`datetime.date.weekday`
    (Monday is 0), and pins a ``WEEKLY`` task to one day."""

    MON = "Mon"
    TUE = "Tue"
    WED = "Wed"
    THU = "Thu"
    FRI = "Fri"
    SAT = "Sat"
    SUN = "Sun"

    @property
    def weekday_index(self) -> int:
        return _WEEKDAY_ORDER.index(self)


_WEEKDAY_ORDER = (
    Weekday.MON,
    Weekday.TUE,
    Weekday.WED,
    Weekday.THU,
    Weekday.FRI,
    Weekday.SAT,
    Weekday.SUN,
)


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
    # The specific calendar day this one-shot task should be worked, distinct
    # from `due_date` (a deadline) and `fixed_time` (a time-of-day anchor).
    # None preserves the original "eligible every day until done" backlog
    # behavior; ignored for recurring tasks, which use `recurs`/`recur_day`
    # instead (see `scheduler.run._eligible_tasks`).
    planned_date: date | None = None
    recurs: Recurrence | None = None
    recur_day: Weekday | None = None
    # Optional link to the Application this task preps for (e.g. "practice
    # Next.js CRUD" -> the Empowerly application), so the optimizer can weigh
    # a task's priority by how soon that application's next interview is.
    application_id: str | None = None
    # Optional link to a specific Interview (a particular round/time), used to
    # bump this task's effective priority as that interview approaches.
    interview_id: str | None = None
    # Optional link to the LeetCode Problem this task practices (e.g. a
    # "Solve: Two Sum" block), so the plan can open the problem directly.
    problem_id: str | None = None
    # Optional link to the MockSession whose scorecard suggested this task
    # (a weak area turned into prep work), so the session can show its follow-up.
    mock_session_id: str | None = None

    def __post_init__(self) -> None:
        if self.est_duration_min <= 0:
            raise ValueError(
                f"est_duration_min must be positive, got {self.est_duration_min!r}"
            )


@dataclass(slots=True)
class Application:
    """A job application in the funnel. Kept separate from :class:`Task` since
    it has its own lifecycle (stage, interview dates); tasks link to it via
    :attr:`Task.application_id` to let the optimizer weigh prep tasks by how
    soon that application's next interview is."""

    company: str
    role: str
    id: str
    stage: ApplicationStage = ApplicationStage.APPLIED
    applied_at: datetime | None = None
    next_interview_at: datetime | None = None
    notes: str | None = None


@dataclass(slots=True)
class Interview:
    """A single upcoming (or past) interview round for an :class:`Application`.

    Kept distinct from ``Application.next_interview_at`` because one company
    can have multiple rounds of different types at different times (e.g. a
    Behavioral round Tuesday and a System Design round Thursday) - a single
    field on Application can't represent that."""

    application_id: str
    category: InterviewCategory
    scheduled_at: datetime
    id: str
    notes: str | None = None
    # Id of the synced Google Calendar event, if any (see
    # adapters/interview_calendar_sync.py). None means never synced.
    google_event_id: str | None = None
    # True only if Dayline itself created google_event_id (via the
    # `+ Interview` form while connected) - False for one auto-discovered
    # from an existing calendar event, which Dayline must never delete.
    # Decides what deleting this interview actually does (api/main.py).
    google_event_owned: bool = False
    # Dismissed from the tracked list without touching the calendar event -
    # the "filter" for a calendar-discovered false positive (a personal call,
    # a duplicate entry). Excluded from list_upcoming(); calendar discovery
    # skips a hidden interview's event so it doesn't reappear.
    hidden: bool = False


@dataclass(slots=True)
class ProblemTag:
    """A topic tag (e.g. "Sliding Window") attachable to many problems."""

    name: str
    id: str
    # Hex color like "#2563eb"; None renders as a neutral chip.
    color: str | None = None


@dataclass(slots=True)
class Problem:
    """A LeetCode problem being practiced. Deliberately not a :class:`Task`:
    a problem is the durable thing (notes, tags, solutions) while a task is
    one scheduled session working on it - tasks link here via
    :attr:`Task.problem_id`."""

    title: str
    difficulty: Difficulty
    id: str
    status: ProblemStatus = ProblemStatus.TODO
    number: int | None = None
    slug: str | None = None
    url: str | None = None
    # 1 (shaky) .. 5 (confident); None means not rated yet.
    confidence: int | None = None
    notes: str = ""
    starred: bool = False
    tag_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Stamped by the service on status transitions (see
    # api/services/problems.py), never by the client.
    last_attempted_at: datetime | None = None
    solved_at: datetime | None = None


@dataclass(slots=True)
class Solution:
    """One approach to a :class:`Problem`. A problem holds many, so
    "different ways of solving it" is first-class rather than one code field."""

    problem_id: str
    title: str
    language: str
    code: str
    id: str
    time_complexity: str | None = None
    space_complexity: str | None = None
    explanation: str = ""
    is_optimal: bool = False
    created_at: datetime | None = None


class MockQuestionSource(StrEnum):
    """Where a :class:`MockQuestion` came from."""

    OWN = "own"
    ONE_POINT_THREE_ACRES = "1point3acres"
    OTHER = "other"


class MockRoundType(StrEnum):
    """The kind of interview round a mock question or rubric is for."""

    AI_ASSISTED_PROJECT = "AI-assisted project"
    ALGORITHM = "Algorithm"
    SYSTEM_DESIGN = "System design"
    DEBUGGING = "Debugging"
    BEHAVIORAL = "Behavioral"


@dataclass(slots=True)
class MockQuestion:
    """An interview question in the private mock bank - remembered from a real
    interview or extracted from a pasted forum post.

    A question reported more than once points at its first copy through
    ``canonical_id``; the first copy has ``canonical_id`` ``None``.
    """

    title: str
    round_type: MockRoundType
    id: str
    source: MockQuestionSource = MockQuestionSource.OWN
    source_url: str | None = None
    company: str | None = None
    role: str | None = None
    prompt_md: str = ""
    constraints: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    language_hint: str | None = None
    # The pasted post as-is (possibly not English), kept so extraction can be
    # re-run or checked later.
    original_text: str = ""
    original_language: str | None = None
    reported_on: date | None = None
    canonical_id: str | None = None
    notes: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class RubricCriterion:
    """One graded dimension of a :class:`MockRubric`. ``key`` is the stable id
    the grader must report back; ``weight`` scales it in the overall score."""

    key: str
    title: str
    description: str
    weight: float = 1.0


@dataclass(slots=True)
class MockRubric:
    """What a round is graded on."""

    name: str
    id: str
    round_type: MockRoundType | None = None
    criteria: list[RubricCriterion] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class MockGuideline:
    """Free-text grading standards (how strict, what "good" looks like),
    reusable across rubrics."""

    name: str
    id: str
    body_md: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class MockSession:
    """One practice attempt. Phase 1 sessions are pasted transcripts."""

    title: str
    id: str
    question_id: str | None = None
    rubric_id: str | None = None
    guideline_id: str | None = None
    transcript: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Evidence:
    """A quote the grader cites. ``verified`` is set by code, not the model:
    True only when the quote actually appears in the transcript."""

    quote: str
    verified: bool


@dataclass(slots=True)
class CriterionScore:
    """The grader's result for one :class:`RubricCriterion` (score 1-4)."""

    key: str
    title: str
    score: int
    evidence: list[Evidence] = field(default_factory=list)
    improvement: str = ""


@dataclass(slots=True)
class WeakArea:
    """Something to practise next, phrased so it can become a prep :class:`Task`."""

    title: str
    why: str
    task_name: str
    category: Category
    est_duration_min: int


@dataclass(slots=True)
class Scorecard:
    """The grader's output for a :class:`MockSession`. ``overall_score`` is the
    weighted mean of criterion scores, computed in code (never by the model)."""

    session_id: str
    id: str
    overall_score: float
    grader_model: str
    summary: str = ""
    criteria: list[CriterionScore] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weak_areas: list[WeakArea] = field(default_factory=list)
    created_at: datetime | None = None


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
