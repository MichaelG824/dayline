"""Staged rounds: a practical coding interview in which each stage adds a
production follow-up to the candidate's own code (an LRU cache gains a TTL,
then sizes, then threads).

A staged problem is content, not code - one folder under
``mock/staged_problems/<id>/``::

    problem.toml          title, pack, round_type, duration_min, summary,
                          open (the file the editor opens), solution (the
                          candidate's files the interviewer reads and that
                          are compared stage to stage)
    starter/              the sandbox's starting files; README.md is the overview
    stages/<n>-<slug>/    one folder per stage, in order:
        stage.toml        title, target_min, [[edge_cases]] {id, title, tests}
        prompt.md         what the candidate is asked, shown once it unlocks
        notes.md          interviewer notes: what to probe, strong vs weak
        tests.py          hidden tests, run in the sandbox and never shown
    reference/stage_<n>.py  a solution as it stands after stage n (for tests)

Generated full-stack problems (``mock/project_gen.py``) are stored per user
in the database instead and become the same :class:`StagedProblem` (stage 1
is the task, stage 2 the change request). Their hidden tests are files in
the stack's test language, so which JUnit cases belong to which stage cannot
be read off the source; validation records them (``Stage.cases``) from real
runs instead.

Generated stages after the first are *timed* (``Stage.unlock_min``): the
change request arrives at its minute whether or not stage 1 has passed, the
way a real interviewer interrupts you. Passing stage 1 early keeps the
candidate on it (polishing) until then, unless they ask for the change
request early (:func:`bring_early`); and a stage 1 that has not passed stays
active after the change request arrives, so its hidden tests keep counting.
Built-in problems have no timed stages and unlock each stage when the one
before it passes.

Everything below the loader is pure: which hidden tests a run includes, how a
run moves the round on, and the per-stage scores.
"""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal

from dayline.models import MockRoundType, StageAttempt, StageStatus

PROBLEMS_DIR = Path(__file__).parent / "staged_problems"
OVERVIEW_FILE = "README.md"
# A later stage that keeps less than this share of the previous stage's code
# lines rewrote the design rather than extending it.
REWRITE_THRESHOLD = 0.5

_STAGE_DIR = re.compile(r"^(\d+)-([a-z0-9][a-z0-9-]*)$")
_TEST_DEF = re.compile(r"^def (test_\w+)\(", re.MULTILINE)

EdgeOutcome = Literal["hit", "caught", "missed", "pending", "not_reached"]
DesignVerdict = Literal["extended", "rewrote"]


@dataclass(frozen=True, slots=True)
class EdgeCase:
    """An edge case a stage's hidden tests check; it counts as handled only
    when every test in ``tests`` passes."""

    id: str
    title: str
    tests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage:
    number: int  # 1-based
    slug: str
    title: str
    target_min: int
    prompt_md: str
    notes_md: str
    # The hidden test files, by path inside the runner's hidden-tests folder.
    tests: dict[str, str]
    edge_cases: tuple[EdgeCase, ...] = ()
    # Generated problems: every hidden test case as (JUnit classname, name),
    # recorded when the problem was validated. Empty for built-in (pytest)
    # stages, whose cases are matched by module name instead.
    cases: frozenset[tuple[str, str]] = frozenset()
    # Generated problems: when the stage unlocks, in minutes into the round
    # (the change request's time; stage 1 starts at 0).
    unlock_min: int | None = None

    @property
    def timed(self) -> bool:
        """Whether the stage arrives at a set minute rather than when the
        stage before it passes."""
        return self.number > 1 and self.unlock_min is not None

    @property
    def test_module(self) -> str:
        """A built-in stage's hidden test module; JUnit classnames start with it."""
        return f"test_stage_{self.number}_{self.slug.replace('-', '_')}"

    @property
    def test_names(self) -> frozenset[str]:
        if self.cases:
            return frozenset(name for _, name in self.cases)
        return frozenset(name for src in self.tests.values() for name in _TEST_DEF.findall(src))

    def owns(self, case: dict[str, Any]) -> bool:
        """Whether a JUnit case from a hidden test run is one of this stage's."""
        classname = str(case.get("classname") or "")
        if self.cases:
            return (classname, str(case.get("name") or "")) in self.cases
        return classname.split(".")[0] == self.test_module

    def case_name(self, case: dict[str, Any]) -> str:
        """The test a case reports on: a parametrized pytest case counts
        toward its function; recorded names are kept whole."""
        name = str(case.get("name") or "")
        return name if self.cases else name.split("[")[0]


@dataclass(frozen=True, slots=True)
class StagedProblem:
    id: str
    title: str
    pack: str
    round_type: MockRoundType
    duration_min: int
    summary: str
    open_path: str
    solution: tuple[str, ...]
    stages: tuple[Stage, ...]
    starter: dict[str, str] = field(default_factory=dict)
    # Stage number -> the reference solution file after that stage.
    references: dict[int, str] = field(default_factory=dict)
    # Generated problems: what the grader should look for in this round.
    analysis_hints: tuple[str, ...] = ()

    @property
    def overview_md(self) -> str:
        return self.starter.get(OVERVIEW_FILE, "")

    @property
    def timed(self) -> bool:
        return any(stage.timed for stage in self.stages)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _read_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _load_stage(folder: Path, number: int, slug: str) -> Stage:
    where = f"{folder.parent.parent.name}/stages/{folder.name}"
    meta = tomllib.loads((folder / "stage.toml").read_text())
    module = f"test_stage_{number}_{slug.replace('-', '_')}"
    stage = Stage(
        number=number,
        slug=slug,
        title=str(meta["title"]),
        target_min=int(meta["target_min"]),
        prompt_md=(folder / "prompt.md").read_text(),
        notes_md=(folder / "notes.md").read_text(),
        tests={f"{module}.py": (folder / "tests.py").read_text()},
        edge_cases=tuple(
            EdgeCase(id=str(e["id"]), title=str(e["title"]), tests=tuple(e["tests"]))
            for e in meta.get("edge_cases", [])
        ),
    )
    if not stage.test_names:
        raise ValueError(f"{where}/tests.py defines no test functions")
    for edge in stage.edge_cases:
        unknown = set(edge.tests) - stage.test_names
        if not edge.tests or unknown:
            raise ValueError(f"{where}: edge case {edge.id!r} names unknown tests {unknown!r}")
    return stage


def _load(folder: Path) -> StagedProblem:
    meta = tomllib.loads((folder / "problem.toml").read_text())
    starter = _read_tree(folder / "starter")
    if OVERVIEW_FILE not in starter:
        raise ValueError(f"Staged problem {folder.name} has no starter/{OVERVIEW_FILE}")
    stages = []
    for stage_dir in sorted((folder / "stages").iterdir(), key=lambda d: d.name):
        match = _STAGE_DIR.match(stage_dir.name)
        if not stage_dir.is_dir() or not match:
            continue
        stages.append(_load_stage(stage_dir, int(match[1]), match[2]))
    if [s.number for s in stages] != list(range(1, len(stages) + 1)):
        raise ValueError(f"Staged problem {folder.name}'s stages must be numbered 1, 2, 3, ...")
    open_path = str(meta["open"])
    solution = tuple(str(p) for p in meta["solution"])
    for path in (open_path, *solution):
        if path not in starter:
            raise ValueError(f"Staged problem {folder.name} names {path}, which is not in starter/")
    references_dir = folder / "reference"
    references = {
        int(p.stem.removeprefix("stage_")): p.read_text()
        for p in sorted(references_dir.glob("stage_*.py"))
    }
    return StagedProblem(
        id=folder.name,
        title=str(meta["title"]),
        pack=str(meta["pack"]),
        round_type=MockRoundType(meta["round_type"]),
        duration_min=int(meta["duration_min"]),
        summary=str(meta.get("summary", "")),
        open_path=open_path,
        solution=solution,
        stages=tuple(stages),
        starter=starter,
        references=references,
    )


@cache
def builtin_staged_problems() -> dict[str, StagedProblem]:
    folders = sorted(d for d in PROBLEMS_DIR.iterdir() if (d / "problem.toml").is_file())
    return {p.id: p for p in map(_load, folders)}


# --------------------------------------------------------------------------- #
# Stage gating
# --------------------------------------------------------------------------- #


def new_round(problem: StagedProblem, now: datetime) -> list[StageAttempt]:
    """Stage 1 active from ``now``; the rest locked."""
    return [
        StageAttempt(status=StageStatus.ACTIVE, started_at=now)
        if stage.number == 1
        else StageAttempt()
        for stage in problem.stages
    ]


def active_index(stages: list[StageAttempt]) -> int | None:
    """The 0-based index of the latest active stage; ``None`` when none is
    active. A pass-to-unlock round has at most one; in a timed round a stage
    that had not passed when the next one arrived stays active behind it."""
    active = [i for i, s in enumerate(stages) if s.status is StageStatus.ACTIVE]
    return active[-1] if active else None


def focus_index(stages: list[StageAttempt]) -> int | None:
    """The stage the candidate is working in: the latest active one, else the
    latest unlocked while a stage is still to come; ``None`` once every stage
    is done. In a pass-to-unlock round that is the active stage. In a timed
    round it can be a passed stage being polished while the next one's time
    has not come yet, or stage 1 again after the change request is skipped."""
    ended = any(s.status is StageStatus.FAILED for s in stages)  # close_round ran
    if ended or not any(s.status in (StageStatus.ACTIVE, StageStatus.LOCKED) for s in stages):
        return None
    active = active_index(stages)
    if active is not None:
        return active
    unlocked = [i for i, s in enumerate(stages) if s.status is not StageStatus.LOCKED]
    return unlocked[-1] if unlocked else None


def next_unlock(
    problem: StagedProblem, stages: list[StageAttempt], round_start: datetime
) -> tuple[int, datetime] | None:
    """The next locked stage and when it arrives, if it is timed."""
    for i, (stage, attempt) in enumerate(zip(problem.stages, stages, strict=True)):
        if attempt.status is StageStatus.LOCKED:
            if not stage.timed or stage.unlock_min is None:
                return None
            return i, round_start + timedelta(minutes=stage.unlock_min)
    return None


def _unlock(stages: list[StageAttempt], index: int, at: datetime) -> None:
    stages[index].status = StageStatus.ACTIVE
    stages[index].started_at = at


def unlock_due(
    problem: StagedProblem, stages: list[StageAttempt], round_start: datetime, now: datetime
) -> list[int]:
    """Unlock every timed stage whose minute has come, whatever state the
    stages before it are in. Each is stamped with its own minute, not
    ``now``: nobody may have asked until later. Returns the indices unlocked."""
    unlocked = []
    while (due := next_unlock(problem, stages, round_start)) is not None and due[1] <= now:
        _unlock(stages, due[0], due[1])
        unlocked.append(due[0])
    return unlocked


def can_bring_early(problem: StagedProblem, stages: list[StageAttempt]) -> bool:
    """Whether the candidate may ask for the next timed stage now: nothing
    is active (every stage so far passed or was skipped) and it is timed."""
    if active_index(stages) is not None:
        return False
    locked = next((i for i, s in enumerate(stages) if s.status is StageStatus.LOCKED), None)
    return locked is not None and problem.stages[locked].timed


def bring_early(problem: StagedProblem, stages: list[StageAttempt], now: datetime) -> int:
    """ "I'm done early": unlock the next timed stage now; returns its index."""
    if not can_bring_early(problem, stages):
        raise ValueError("Nothing to bring early: finish or skip the current stage first")
    index = next(i for i, s in enumerate(stages) if s.status is StageStatus.LOCKED)
    _unlock(stages, index, now)
    return index


def hidden_files(problem: StagedProblem, stages: list[StageAttempt]) -> dict[str, str]:
    """The hidden tests for a run: the active stages' plus every passed
    stage's (so a later stage cannot quietly break an earlier one). Skipped
    stages are left out - their features may never have been written."""
    return {
        path: source
        for stage, attempt in zip(problem.stages, stages, strict=True)
        if attempt.status in (StageStatus.ACTIVE, StageStatus.PASSED)
        for path, source in stage.tests.items()
    }


def _case_stage(problem: StagedProblem, case: dict[str, Any]) -> Stage | None:
    return next((s for s in problem.stages if s.owns(case)), None)


_OUTCOME_RANK = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


def stage_outcomes(
    problem: StagedProblem, stage: Stage, report: dict[str, Any] | None
) -> dict[str, str]:
    """``{test function: outcome}`` for one stage's tests in a run. A
    parametrized test takes its worst case's outcome."""
    outcomes: dict[str, str] = {}
    cases = (report or {}).get("cases")
    for case in cases if isinstance(cases, list) else []:
        if not isinstance(case, dict) or _case_stage(problem, case) is not stage:
            continue
        name = stage.case_name(case)
        outcome = str(case.get("outcome") or "error")
        if _OUTCOME_RANK.get(outcome, 3) >= _OUTCOME_RANK.get(outcomes.get(name, "passed"), 3):
            outcomes[name] = outcome
    return outcomes


def _all_passed(problem: StagedProblem, stage: Stage, report: dict[str, Any] | None) -> bool:
    outcomes = stage_outcomes(problem, stage, report)
    return all(outcomes.get(name) == "passed" for name in stage.test_names)


def run_passes(problem: StagedProblem, stage: Stage, report: dict[str, Any]) -> bool:
    """Whether a run passes ``stage``: the whole run passed (earlier stages
    included) and every one of the stage's own tests actually ran and passed."""
    if report.get("status") != "passed":
        return False
    return _all_passed(problem, stage, report)


def _passes_through(
    problem: StagedProblem, stages: list[StageAttempt], index: int, report: dict[str, Any]
) -> bool:
    """A timed round's rule: the run passes stage ``index`` when its own
    tests and those of every earlier stage it includes passed. A later stage
    still failing does not hold an earlier one back."""
    if report.get("status") not in ("passed", "failed"):
        return False
    return all(
        _all_passed(problem, stage, report)
        for stage, attempt in zip(problem.stages[: index + 1], stages, strict=False)
        if attempt.status in (StageStatus.ACTIVE, StageStatus.PASSED)
    )


def record_run(
    problem: StagedProblem, stages: list[StageAttempt], report: dict[str, Any]
) -> list[int]:
    """Record a hidden test run on the stages it was for (the focus stage
    and any other still active); returns the indices of the active stages it
    passes. The caller then finishes them (it needs the code)."""
    focus = focus_index(stages)
    if focus is None:
        raise ValueError("Every stage is already done")
    active = [i for i, s in enumerate(stages) if s.status is StageStatus.ACTIVE]
    for i in sorted({focus, *active}):
        attempt = stages[i]
        attempt.runs += 1
        attempt.report = report
        if attempt.runs == 1:
            attempt.first_outcomes = stage_outcomes(problem, problem.stages[i], report)
    if not problem.timed:
        return [i for i in active if run_passes(problem, problem.stages[i], report)]
    return [i for i in active if _passes_through(problem, stages, i, report)]


def finish_stage(
    problem: StagedProblem,
    stages: list[StageAttempt],
    index: int,
    status: StageStatus,
    code: dict[str, str],
    now: datetime,
) -> None:
    """Close an active stage as passed or skipped. The next stage unlocks
    now unless it is timed and this one passed: a timed stage waits for its
    minute (skipping is moving on, so it brings the next stage at once)."""
    if status not in (StageStatus.PASSED, StageStatus.SKIPPED):
        raise ValueError(f"A stage cannot finish as {status}")
    attempt = stages[index]
    if attempt.status is not StageStatus.ACTIVE:
        raise ValueError(f"Stage {index + 1} is not active")
    attempt.status, attempt.finished_at, attempt.code = status, now, code
    after = index + 1
    waits = status is StageStatus.PASSED and after < len(stages) and problem.stages[after].timed
    if after < len(stages) and stages[after].status is StageStatus.LOCKED and not waits:
        _unlock(stages, after, now)


def close_round(stages: list[StageAttempt], code: dict[str, str], now: datetime) -> None:
    """The round ended: a stage still active did not pass."""
    for attempt in stages:
        if attempt.status is StageStatus.ACTIVE:
            attempt.status, attempt.finished_at, attempt.code = StageStatus.FAILED, now, code


def solution_files(problem: StagedProblem, files: dict[str, str]) -> dict[str, str]:
    """The candidate's solution files out of a workspace snapshot."""
    return {path: files[path] for path in problem.solution if path in files}


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EdgeResult:
    """``hit``: handled before the tests said anything (passed on the stage's
    first run). ``caught``: failed the first run, fixed later. ``missed``:
    never passed. ``pending``: the stage is still active. ``not_reached``:
    the round ended before this stage."""

    id: str
    title: str
    outcome: EdgeOutcome


@dataclass(frozen=True, slots=True)
class DesignChange:
    """How much of the previous stage's code survived into this one."""

    kept: float
    verdict: DesignVerdict


@dataclass(frozen=True, slots=True)
class StageResult:
    number: int
    title: str
    status: StageStatus
    target_min: int
    time_spent_s: float | None
    runs: int
    edge_cases: tuple[EdgeResult, ...]
    design: DesignChange | None


def _code_lines(files: dict[str, str]) -> list[str]:
    """Meaningful lines of code, whitespace-insensitive."""
    lines = []
    for path in sorted(files):
        for raw in files[path].splitlines():
            line = " ".join(raw.split())
            if line and not line.startswith("#"):
                lines.append(line)
    return lines


def design_change(before: dict[str, str], after: dict[str, str]) -> DesignChange | None:
    """Did a stage extend the previous stage's code or rewrite it? Measured
    as the share of the earlier code's lines that are still there, in order.
    ``None`` when there is nothing to compare, or the code did not change (a
    stage skipped or ended untouched neither extended nor rewrote anything)."""
    old, new = _code_lines(before), _code_lines(after)
    if not old or not new or old == new:
        return None
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    kept = sum(block.size for block in matcher.get_matching_blocks()) / len(old)
    return DesignChange(kept=kept, verdict="extended" if kept >= REWRITE_THRESHOLD else "rewrote")


def _edge_outcome(
    problem: StagedProblem, stage: Stage, attempt: StageAttempt, edge: EdgeCase
) -> EdgeOutcome:
    if attempt.status is StageStatus.LOCKED:
        return "not_reached"

    def all_passed(outcomes: dict[str, str]) -> bool:
        return all(outcomes.get(test) == "passed" for test in edge.tests)

    if attempt.first_outcomes and all_passed(attempt.first_outcomes):
        return "hit"
    if all_passed(stage_outcomes(problem, stage, attempt.report)):
        return "caught"
    return "pending" if attempt.status is StageStatus.ACTIVE else "missed"


def score_round(
    problem: StagedProblem, stages: list[StageAttempt], now: datetime
) -> list[StageResult]:
    """Per stage: status, time spent, test runs, edge cases, and whether its
    code extended the previous stage's design. ``now`` ends the clock of a
    stage still active."""
    results = []
    for i, (stage, attempt) in enumerate(zip(problem.stages, stages, strict=True)):
        spent = None
        if attempt.started_at is not None:
            spent = ((attempt.finished_at or now) - attempt.started_at).total_seconds()
        design = None
        if i > 0 and attempt.status is not StageStatus.LOCKED:
            design = design_change(stages[i - 1].code, attempt.code)
        results.append(
            StageResult(
                number=stage.number,
                title=stage.title,
                status=attempt.status,
                target_min=stage.target_min,
                time_spent_s=spent,
                runs=attempt.runs,
                edge_cases=tuple(
                    EdgeResult(edge.id, edge.title, _edge_outcome(problem, stage, attempt, edge))
                    for edge in stage.edge_cases
                ),
                design=design,
            )
        )
    return results


_EDGE_WORDS: dict[EdgeOutcome, str] = {
    "hit": "handled up front",
    "caught": "fixed after a failing run",
    "missed": "missed",
    "pending": "not yet passing",
    "not_reached": "not reached",
}


def _minutes(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def round_record(problem: StagedProblem, stages: list[StageAttempt], now: datetime) -> str:
    """The staged results as text, for the grader's work record."""
    lines = [f"## Staged round: {problem.title}"]
    start = stages[0].started_at if stages else None
    for stage, attempt, result in zip(
        problem.stages, stages, score_round(problem, stages, now), strict=True
    ):
        head = f"Stage {result.number} ({result.title}): {result.status.value}"
        if stage.timed and attempt.started_at is not None and start is not None:
            arrived = _minutes((attempt.started_at - start).total_seconds())
            head += (
                f" (the change request; arrived at {arrived}, scheduled {stage.unlock_min:02d}:00)"
            )
        if result.time_spent_s is not None:
            head += f" after {_minutes(result.time_spent_s)} (target {result.target_min} min)"
        head += f", {result.runs} hidden test run{'' if result.runs == 1 else 's'}"
        if result.design is not None:
            head += (
                f"; {result.design.verdict} the stage {result.number - 1} design "
                f"({round(result.design.kept * 100)}% of its code lines kept)"
            )
        lines.append(head)
        lines += [f"- {e.title}: {_EDGE_WORDS[e.outcome]}" for e in result.edge_cases]
    return "\n".join(lines)
