"""Objective numbers about an AI-assisted round, computed in code so the
grader cites them instead of counting events itself: how the candidate
oriented before changing code, how they prompted the assistant, how they
reviewed its diffs, how they verified, how they took the change request, how
they spent their time, and where both stages ended.

Pure functions over the session's events and stage results - no I/O.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from dayline.mock.staged import StagedProblem, round_record, stage_outcomes
from dayline.mock.worklog import work_record
from dayline.models import MockEvent, MockEventKind, MockSession, StageAttempt, StageStatus

# An accepted edit reviewed faster than this was most likely not read.
QUICK_REVIEW_S = 10.0
# A stretch with no activity this long is worth pointing out.
LONG_GAP_S = 6 * 60
# A prompt naming a path, a file, or a `code identifier` is scoped.
_SCOPED = re.compile(r"`[^`]+`|\b[\w./-]+\.(?:ts|tsx|js|rb|py|erb|json|css|md|sql)\b|\w+/\w+")

_ACTIVITY = frozenset(
    {
        MockEventKind.FILE_SAVED,
        MockEventKind.TESTS_RUN,
        MockEventKind.STAGE_TESTS_RUN,
        MockEventKind.COMMAND_RUN,
        MockEventKind.CANDIDATE_MESSAGE,
        MockEventKind.ASSISTANT_PROMPT,
        MockEventKind.ASSISTANT_EDIT_DECIDED,
        MockEventKind.SERVER_ACTION,
        MockEventKind.PREVIEW_RELOADED,
    }
)
_RUNS = frozenset({MockEventKind.TESTS_RUN, MockEventKind.STAGE_TESTS_RUN})
_CHECKS = _RUNS | {MockEventKind.PREVIEW_RELOADED}


@dataclass(frozen=True, slots=True)
class StageEnd:
    number: int
    title: str
    status: StageStatus
    # The stage's own hidden tests in the round's last hidden run.
    tests_passed: int
    tests_total: int
    time_spent_s: float | None
    target_min: int


@dataclass(slots=True)
class RoundMetrics:
    """Seconds are from the start of the round unless named ``*_after_*``."""

    duration_s: float
    # Orientation
    first_save_s: float | None = None
    prompts_before_first_save: int = 0
    checks_before_first_save: int = 0
    # Prompting
    prompts: dict[str, int] = field(default_factory=lambda: {"ask": 0, "plan": 0, "edit": 0})
    median_prompt_words: float | None = None
    scoped_prompts: int = 0
    edit_prompts_after_plan: int = 0
    # Reviewing the assistant's diffs
    proposed: int = 0
    accepted: int = 0
    rejected: int = 0
    conflicted: int = 0
    never_reviewed: int = 0
    quick_accepts: int = 0
    median_accept_review_s: float | None = None
    # Accepted edits followed by a test run or preview reload before the next accept.
    verified_accepts: int = 0
    # Verifying
    test_runs: int = 0
    hidden_runs: int = 0
    preview_reloads: int = 0
    runs_after_last_save: int = 0
    # The change request
    change_request_s: float | None = None
    change_request_early: bool = False
    first_action_after_cr_s: float | None = None
    first_action_after_cr: str | None = None
    first_save_after_cr_s: float | None = None
    first_prompt_after_cr_mode: str | None = None
    questions_after_cr: int = 0
    # Time
    longest_gap_s: float = 0.0
    longest_gap_at_s: float | None = None
    stages: list[StageEnd] = field(default_factory=list)


def _t(event: MockEvent, start: datetime) -> float:
    return max(0.0, (event.at - start).total_seconds()) if event.at else 0.0


def _action(event: MockEvent) -> str:
    d = event.data
    if event.kind is MockEventKind.FILE_SAVED:
        return f"saved {d.get('path')}"
    if event.kind is MockEventKind.ASSISTANT_PROMPT:
        return f"asked the AI ({d.get('mode')} mode)"
    if event.kind is MockEventKind.CANDIDATE_MESSAGE:
        return "spoke to the interviewer"
    if event.kind in _RUNS:
        return "ran the tests"
    if event.kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
        return f"{d.get('decision')} an AI edit"
    if event.kind is MockEventKind.COMMAND_RUN:
        return f"ran `{d.get('command')}`"
    return "used the app preview"


def compute(
    problem: StagedProblem | None,
    stages: list[StageAttempt],
    events: list[MockEvent],
    start: datetime,
    end: datetime,
) -> RoundMetrics:
    m = RoundMetrics(duration_s=max(0.0, (end - start).total_seconds()))
    timed = sorted(events, key=lambda e: e.at or start)

    saves = [e for e in timed if e.kind is MockEventKind.FILE_SAVED]
    first_save = _t(saves[0], start) if saves else None
    m.first_save_s = first_save
    before_first = [e for e in timed if first_save is None or _t(e, start) < first_save]
    m.prompts_before_first_save = sum(
        e.kind is MockEventKind.ASSISTANT_PROMPT for e in before_first
    )
    m.checks_before_first_save = sum(e.kind in _CHECKS for e in before_first)

    unlocked = next((e for e in timed if e.kind is MockEventKind.STAGE_UNLOCKED), None)
    cr = _t(unlocked, start) if unlocked else None
    m.change_request_s = cr
    m.change_request_early = bool(unlocked and unlocked.data.get("early"))

    def phase(e: MockEvent) -> int:
        return 0 if cr is None or _t(e, start) < cr else 1

    prompts = [e for e in timed if e.kind is MockEventKind.ASSISTANT_PROMPT]
    for p in prompts:
        mode = str(p.data.get("mode"))
        m.prompts[mode] = m.prompts.get(mode, 0) + 1
    words = [len(str(p.data.get("text", "")).split()) for p in prompts]
    m.median_prompt_words = statistics.median(words) if words else None
    m.scoped_prompts = sum(bool(_SCOPED.search(str(p.data.get("text", "")))) for p in prompts)
    planned: set[int] = set()
    for p in prompts:
        if p.data.get("mode") == "plan":
            planned.add(phase(p))
        elif p.data.get("mode") == "edit" and phase(p) in planned:
            m.edit_prompts_after_plan += 1

    proposals = {
        e.data.get("proposalId") for e in timed if e.kind is MockEventKind.ASSISTANT_EDIT_PROPOSED
    }
    final: dict[object, MockEvent] = {}
    for e in timed:
        if e.kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
            final[e.data.get("proposalId")] = e
    m.proposed = len(proposals)
    accepts = [e for e in final.values() if e.data.get("decision") == "accepted"]
    m.accepted = len(accepts)
    m.rejected = sum(e.data.get("decision") == "rejected" for e in final.values())
    m.conflicted = sum(e.data.get("decision") == "conflict" for e in final.values())
    m.never_reviewed = len(proposals - set(final))
    reviews = [
        float(e.data["reviewMs"]) / 1000
        for e in accepts
        if isinstance(e.data.get("reviewMs"), int | float)
    ]
    m.quick_accepts = sum(r < QUICK_REVIEW_S for r in reviews)
    m.median_accept_review_s = statistics.median(reviews) if reviews else None
    accept_times = sorted(_t(e, start) for e in accepts)
    check_times = [_t(e, start) for e in timed if e.kind in _CHECKS]
    for i, at in enumerate(accept_times):
        until = accept_times[i + 1] if i + 1 < len(accept_times) else float("inf")
        if any(at <= c < until for c in check_times):
            m.verified_accepts += 1

    m.test_runs = sum(e.kind is MockEventKind.TESTS_RUN for e in timed)
    m.hidden_runs = sum(e.kind is MockEventKind.STAGE_TESTS_RUN for e in timed)
    m.preview_reloads = sum(e.kind is MockEventKind.PREVIEW_RELOADED for e in timed)
    last_save = _t(saves[-1], start) if saves else None
    m.runs_after_last_save = sum(
        e.kind in _RUNS and (last_save is None or _t(e, start) >= last_save) for e in timed
    )

    if cr is not None:
        after = [e for e in timed if e.kind in _ACTIVITY and _t(e, start) >= cr]
        if after:
            m.first_action_after_cr_s = _t(after[0], start) - cr
            m.first_action_after_cr = _action(after[0])
        save_after = next((e for e in after if e.kind is MockEventKind.FILE_SAVED), None)
        if save_after is not None:
            m.first_save_after_cr_s = _t(save_after, start) - cr
        prompt_after = next((e for e in after if e.kind is MockEventKind.ASSISTANT_PROMPT), None)
        if prompt_after is not None:
            m.first_prompt_after_cr_mode = str(prompt_after.data.get("mode"))
        m.questions_after_cr = sum(
            e.kind is MockEventKind.CANDIDATE_MESSAGE and "?" in str(e.data.get("text", ""))
            for e in after
        )

    moments = [0.0, *(_t(e, start) for e in timed if e.kind in _ACTIVITY), m.duration_s]
    moments.sort()
    for a, b in zip(moments, moments[1:], strict=False):
        if b - a > m.longest_gap_s:
            m.longest_gap_s, m.longest_gap_at_s = b - a, a

    if problem is not None:
        last_report = next((a.report for a in reversed(stages) if a.report), None)
        for stage, attempt in zip(problem.stages, stages, strict=True):
            outcomes = stage_outcomes(problem, stage, last_report)
            spent = None
            if attempt.started_at is not None:
                spent = ((attempt.finished_at or end) - attempt.started_at).total_seconds()
            m.stages.append(
                StageEnd(
                    number=stage.number,
                    title=stage.title,
                    status=attempt.status,
                    tests_passed=sum(outcomes.get(n) == "passed" for n in stage.test_names),
                    tests_total=len(stage.test_names),
                    time_spent_s=spent,
                    target_min=stage.target_min,
                )
            )
    return m


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _share(part: int, whole: int) -> str:
    return f"{part}/{whole} ({round(100 * part / whole)}%)" if whole else "0/0"


def _span(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def metrics_text(m: RoundMetrics) -> str:
    """The metrics for the grader's work record. Times are ``mm:ss`` from
    the start, matching the timeline, so they can be cited."""
    total_prompts = sum(m.prompts.values())
    lines = ["## Round metrics (computed in code; cite them, do not recount)"]
    lines.append(
        f"- Orientation: first save at {clock(m.first_save_s)}; before it, "
        f"{m.prompts_before_first_save} AI prompts and {m.checks_before_first_save} test "
        "runs or preview reloads."
    )
    lines.append(
        f"- Prompts: {total_prompts} (ask {m.prompts.get('ask', 0)}, plan "
        f"{m.prompts.get('plan', 0)}, edit {m.prompts.get('edit', 0)}); median "
        f"{m.median_prompt_words if m.median_prompt_words is not None else 0:g} words; "
        f"{_share(m.scoped_prompts, total_prompts)} name a file, path, or identifier; "
        f"{_share(m.edit_prompts_after_plan, m.prompts.get('edit', 0))} edit prompts had a "
        "plan prompt before them in the same part of the round."
    )
    review = (
        f"median {m.median_accept_review_s:.1f}s" if m.median_accept_review_s is not None else "-"
    )
    lines.append(
        f"- AI diffs: {m.proposed} proposed; {m.accepted} accepted, {m.rejected} rejected, "
        f"{m.conflicted} conflicted, {m.never_reviewed} never reviewed. Accepted edits "
        f"reviewed under {QUICK_REVIEW_S:g}s: {_share(m.quick_accepts, m.accepted)}; review "
        f"time {review}. Accepted edits followed by a test run or preview reload before the "
        f"next accept: {_share(m.verified_accepts, m.accepted)}."
    )
    lines.append(
        f"- Verification: {m.test_runs} visible test runs, {m.hidden_runs} hidden test runs, "
        f"{m.preview_reloads} preview reloads; {m.runs_after_last_save} test runs after the "
        "last save."
    )
    if m.change_request_s is not None:
        when = "early, at the candidate's request" if m.change_request_early else "on schedule"
        lines.append(
            f"- Change request: arrived at {clock(m.change_request_s)} ({when}); first action "
            f"{_span(m.first_action_after_cr_s)} later ({m.first_action_after_cr or 'none'}); "
            f"first save {_span(m.first_save_after_cr_s)} later; first AI prompt after it: "
            f"{m.first_prompt_after_cr_mode or 'none'} mode; {m.questions_after_cr} questions "
            "to the interviewer after it."
        )
    gap = (
        f"longest stretch without activity {_span(m.longest_gap_s)} from "
        f"{clock(m.longest_gap_at_s)}"
    )
    lines.append(f"- Time: round length {clock(m.duration_s)}; {gap}.")
    for s in m.stages:
        spent = (
            f"{_span(s.time_spent_s)} (target {s.target_min} min)"
            if s.time_spent_s is not None
            else "not reached"
        )
        lines.append(
            f"- Stage {s.number} ({s.title}) final: {s.status.value}; its hidden tests in the "
            f"last run: {s.tests_passed}/{s.tests_total} passing; time {spent}."
        )
    return "\n".join(lines)


def analysis_record(
    problem: StagedProblem | None, session: MockSession, events: list[MockEvent], now: datetime
) -> str:
    """The work record an AI-assisted round is analysed on: the stage
    results, these metrics, then the timeline, AI log, tests, and diff."""
    parts = []
    if problem is not None:
        parts.append(round_record(problem, session.stages, now))
    if session.started_at is not None:
        parts.append(
            metrics_text(compute(problem, session.stages, events, session.started_at, now))
        )
    parts.append(work_record(session, events))
    return "\n\n".join(parts)
