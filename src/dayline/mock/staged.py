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

Everything below the loader is pure: which hidden tests a run includes, how a
run moves the round on, and the per-stage scores.
"""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
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
    tests: str  # The hidden test file's source.
    edge_cases: tuple[EdgeCase, ...] = ()

    @property
    def test_module(self) -> str:
        """The hidden test file's module name; JUnit classnames start with it."""
        return f"test_stage_{self.number}_{self.slug.replace('-', '_')}"

    @property
    def test_names(self) -> frozenset[str]:
        return frozenset(_TEST_DEF.findall(self.tests))


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

    @property
    def overview_md(self) -> str:
        return self.starter.get(OVERVIEW_FILE, "")


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
    stage = Stage(
        number=number,
        slug=slug,
        title=str(meta["title"]),
        target_min=int(meta["target_min"]),
        prompt_md=(folder / "prompt.md").read_text(),
        notes_md=(folder / "notes.md").read_text(),
        tests=(folder / "tests.py").read_text(),
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
    """The 0-based index of the active stage; ``None`` once every stage is done."""
    return next((i for i, s in enumerate(stages) if s.status is StageStatus.ACTIVE), None)


def hidden_files(problem: StagedProblem, stages: list[StageAttempt]) -> dict[str, str]:
    """The hidden tests for a run: the active stage's plus every passed
    stage's (so a later stage cannot quietly break an earlier one). Skipped
    stages are left out - their features may never have been written."""
    return {
        f"{stage.test_module}.py": stage.tests
        for stage, attempt in zip(problem.stages, stages, strict=True)
        if attempt.status in (StageStatus.ACTIVE, StageStatus.PASSED)
    }


def _case_stage(problem: StagedProblem, case: dict[str, Any]) -> Stage | None:
    module = str(case.get("classname") or "").split(".")[0]
    return next((s for s in problem.stages if s.test_module == module), None)


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
        name = str(case.get("name") or "").split("[")[0]
        outcome = str(case.get("outcome") or "error")
        if _OUTCOME_RANK.get(outcome, 3) >= _OUTCOME_RANK.get(outcomes.get(name, "passed"), 3):
            outcomes[name] = outcome
    return outcomes


def run_passes(problem: StagedProblem, stage: Stage, report: dict[str, Any]) -> bool:
    """Whether a run passes ``stage``: the whole run passed (earlier stages
    included) and every one of the stage's own tests actually ran and passed."""
    if report.get("status") != "passed":
        return False
    outcomes = stage_outcomes(problem, stage, report)
    return all(outcomes.get(name) == "passed" for name in stage.test_names)


def record_run(
    problem: StagedProblem, stages: list[StageAttempt], report: dict[str, Any]
) -> bool:
    """Record a hidden test run on the active stage; returns whether it
    passed that stage. The caller then finishes the stage (it needs the code)."""
    index = active_index(stages)
    if index is None:
        raise ValueError("Every stage is already done")
    attempt, stage = stages[index], problem.stages[index]
    attempt.runs += 1
    attempt.report = report
    if attempt.runs == 1:
        attempt.first_outcomes = stage_outcomes(problem, stage, report)
    return run_passes(problem, stage, report)


def finish_stage(
    stages: list[StageAttempt], status: StageStatus, code: dict[str, str], now: datetime
) -> None:
    """Close the active stage as passed or skipped and unlock the next one."""
    if status not in (StageStatus.PASSED, StageStatus.SKIPPED):
        raise ValueError(f"A stage cannot finish as {status}")
    index = active_index(stages)
    if index is None:
        raise ValueError("Every stage is already done")
    attempt = stages[index]
    attempt.status, attempt.finished_at, attempt.code = status, now, code
    if index + 1 < len(stages):
        stages[index + 1].status = StageStatus.ACTIVE
        stages[index + 1].started_at = now


def close_round(stages: list[StageAttempt], code: dict[str, str], now: datetime) -> None:
    """The round ended: a stage still active did not pass."""
    index = active_index(stages)
    if index is not None:
        attempt = stages[index]
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
    as the share of the earlier code's lines that are still there, in order."""
    old, new = _code_lines(before), _code_lines(after)
    if not old or not new:
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
    for result in score_round(problem, stages, now):
        head = f"Stage {result.number} ({result.title}): {result.status.value}"
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
