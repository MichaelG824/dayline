"""Staged rounds: a live session whose interviewer adds production follow-ups
to the candidate's own code, stage by stage (see ``mock/staged.py``).

The round runs in an ordinary live-session sandbox, so files, the terminal,
resuming, and ending go through ``services/mock_live.py``. This module adds
what is staged about it: hidden test runs that gate each stage, skipping,
bringing a timed change request early, and the interviewer's turns. Timed
stages unlock on read (``services/staged_clock.py``). The stage state lives on the session
(``MockSession.stages``); transitions, runs, and the chat are also recorded
as session events, which the grader reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import anthropic
from fastapi import HTTPException

from dayline.api.context import AppContext
from dayline.api.serializers import staged_round_json
from dayline.api.services.mock import check_session_refs
from dayline.api.services.mock_live import (
    event,
    live_session,
    new_preview_base,
    runner_errors,
    sandbox_client,
)
from dayline.api.services.staged_clock import catch_up
from dayline.api.services.staged_problems import find_problem, session_problem
from dayline.mock import mock_model, staged
from dayline.mock.interviewer import (
    ChatMessage,
    InterviewerError,
    Trigger,
    interviewer_reply,
    read_signals,
    should_check_in,
)
from dayline.mock.staged import StagedProblem
from dayline.models import (
    InterviewerStyle,
    MockEvent,
    MockEventKind,
    MockSession,
    MockSessionKind,
    MockSessionStatus,
    StageStatus,
)

MAX_MESSAGE_CHARS = 4000


def problem_of(ctx: AppContext, session: MockSession) -> StagedProblem:
    problem = session_problem(ctx, session)
    if problem is None:
        raise HTTPException(
            status_code=410, detail=f"The staged problem {session.staged_problem_id!r} is gone"
        )
    return problem


def _staged_session(ctx: AppContext, session_id: str) -> tuple[MockSession, StagedProblem]:
    """A staged round still in progress, with its due stages unlocked, or a 404/409."""
    session = live_session(ctx, session_id)
    if not session.staged_problem_id:
        raise HTTPException(status_code=404, detail="Not a staged round")
    problem = problem_of(ctx, session)
    catch_up(ctx, session, problem)
    return session, problem


def style_of(session: MockSession) -> InterviewerStyle:
    return session.interviewer_style or InterviewerStyle.COACH


def round_json(ctx: AppContext, session: MockSession, problem: StagedProblem) -> dict[str, Any]:
    events = ctx.mock_source.list_events(session.id)
    return staged_round_json(problem, session, events, datetime.now(UTC))


def start_round(
    ctx: AppContext,
    problem_id: str,
    question_id: str | None,
    rubric_id: str | None,
    guideline_id: str | None,
    style: InterviewerStyle | None = None,
) -> str:
    """Create the session and its sandbox with stage 1 active; returns the
    session id. If the sandbox cannot start, the session is not kept. The
    interviewer is realistic by default in timed (generated) rounds and a
    coach in built-in ones."""
    sandbox = sandbox_client(ctx)
    problem = find_problem(ctx, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail=f"No staged problem {problem_id!r}")
    check_session_refs(ctx, question_id, rubric_id, guideline_id)
    if style is None:
        style = InterviewerStyle.REALISTIC if problem.timed else InterviewerStyle.COACH

    now = datetime.now(UTC)
    session = ctx.mock_source.create_session(
        MockSession(
            id=str(uuid.uuid4()),
            title=problem.title,
            question_id=question_id or None,
            rubric_id=rubric_id or None,
            guideline_id=guideline_id or None,
            kind=MockSessionKind.LIVE,
            status=MockSessionStatus.LIVE,
            pack=problem.pack,
            started_at=now,
            staged_problem_id=problem.id,
            stages=staged.new_round(problem, now),
            # Coach is the default for a missing style, so only realistic is stored.
            interviewer_style=style if style is InterviewerStyle.REALISTIC else None,
        )
    )
    try:
        with runner_errors():
            sandbox.create(
                session.id, problem.pack, problem.starter, new_preview_base(session.id)
            )
    except HTTPException:
        ctx.mock_source.delete_session(session.id)
        raise
    event(
        ctx,
        session.id,
        MockEventKind.SESSION_STARTED,
        stagedProblem=problem.id,
        interviewerStyle=style.value,
    )
    return session.id


def _solution(ctx: AppContext, session_id: str, problem: StagedProblem) -> dict[str, str]:
    """The candidate's solution files as they are in the sandbox now."""
    with runner_errors():
        files: dict[str, str] = sandbox_client(ctx).snapshot(session_id)["files"]
    return staged.solution_files(problem, files)


def _focus(session: MockSession) -> int:
    index = staged.focus_index(session.stages)
    if index is None:
        raise HTTPException(status_code=409, detail="Every stage is done. End the round.")
    return index


def run_stage_tests(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Run the hidden tests of the stage the candidate is in, plus every
    other active or passed stage's. Each active stage the run passes is
    finished; the next stage unlocks then, or at its minute if it is timed."""
    session, problem = _staged_session(ctx, session_id)
    index = _focus(session)
    with runner_errors():
        report = sandbox_client(ctx).run_hidden_tests(
            session_id, staged.hidden_files(problem, session.stages)
        )
    passed = staged.record_run(problem, session.stages, report)
    event(
        ctx,
        session_id,
        MockEventKind.STAGE_TESTS_RUN,
        stage=index + 1,
        status=report.get("status"),
        passed=report.get("passed", 0),
        failed=report.get("failed", 0),
        errors=report.get("errors", 0),
    )
    if passed:
        code = _solution(ctx, session_id, problem)
        now = datetime.now(UTC)
        for i in passed:
            staged.finish_stage(problem, session.stages, i, StageStatus.PASSED, code, now)
            event(ctx, session_id, MockEventKind.STAGE_PASSED, stage=i + 1)
    session.test_report = report
    ctx.mock_source.update_session(session)
    return {
        "report": report,
        "passed": index in passed,
        "staged": round_json(ctx, session, problem),
    }


def skip_stage(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Move on without passing the latest active stage; recorded as
    skipped. In a timed round that also brings the next stage at once."""
    session, problem = _staged_session(ctx, session_id)
    index = staged.active_index(session.stages)
    if index is None:
        raise HTTPException(status_code=409, detail="No stage is in progress")
    code = _solution(ctx, session_id, problem)
    waiting = staged.next_unlock(problem, session.stages, session.started_at or datetime.now(UTC))
    now = datetime.now(UTC)
    staged.finish_stage(problem, session.stages, index, StageStatus.SKIPPED, code, now)
    ctx.mock_source.update_session(session)
    event(ctx, session_id, MockEventKind.STAGE_SKIPPED, stage=index + 1)
    if waiting is not None and session.stages[waiting[0]].status is StageStatus.ACTIVE:
        event(ctx, session_id, MockEventKind.STAGE_UNLOCKED, stage=waiting[0] + 1, early=True)
    return round_json(ctx, session, problem)


def bring_early(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """"I'm done early, bring the change request": unlock the next timed
    stage now. Only once every stage so far has passed (or was skipped)."""
    session, problem = _staged_session(ctx, session_id)
    if not staged.can_bring_early(problem, session.stages):
        raise HTTPException(
            status_code=409, detail="There is no change request to bring in right now"
        )
    index = staged.bring_early(problem, session.stages, datetime.now(UTC))
    ctx.mock_source.update_session(session)
    event(ctx, session_id, MockEventKind.STAGE_UNLOCKED, stage=index + 1, early=True)
    return round_json(ctx, session, problem)


def _chat(events: list[MockEvent]) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="interviewer" if e.kind is MockEventKind.INTERVIEWER_MESSAGE else "candidate",
            text=str(e.data.get("text", "")),
            stage=int(e.data.get("stage") or 0),
        )
        for e in events
        if e.kind in (MockEventKind.INTERVIEWER_MESSAGE, MockEventKind.CANDIDATE_MESSAGE)
    ]


def _opened(events: list[MockEvent], stage: int) -> bool:
    """Whether the interviewer already opened ``stage`` (0 = the closing)."""
    return any(
        e.kind is MockEventKind.INTERVIEWER_MESSAGE
        and e.data.get("trigger") == "stage_start"
        and e.data.get("stage") == stage
        for e in events
    )


def interviewer_turn(
    ctx: AppContext, session_id: str, trigger: Trigger, message: str | None
) -> dict[str, Any]:
    """One interviewer reply. ``stage_start`` opens the stage the candidate
    is in (delivers the change request, or closes the round once every stage
    is done) and happens once per stage, so a reload never repeats it;
    ``follow_up`` asks the next question; ``message`` records the
    candidate's message first, then replies to it; ``check_in`` says
    something only when the candidate is clearly stuck (and otherwise
    returns the round unchanged without a model call). The candidate's
    message is kept even if the reply fails, and ``message`` with no text
    retries the reply to it."""
    session, problem = _staged_session(ctx, session_id)
    index = staged.focus_index(session.stages)
    # Messages are filed under the active stage; 0 once every stage is done.
    number = 0 if index is None else index + 1
    text = (message or "").strip()
    if trigger == "message" and text:
        if len(text) > MAX_MESSAGE_CHARS:
            raise HTTPException(
                status_code=400, detail=f"Keep messages under {MAX_MESSAGE_CHARS} characters"
            )
        event(ctx, session_id, MockEventKind.CANDIDATE_MESSAGE, stage=number, text=text)

    events = ctx.mock_source.list_events(session_id)
    chat = _chat(events)
    if trigger == "message" and (not chat or chat[-1].role != "candidate"):
        raise HTTPException(status_code=400, detail="Write a message first")
    if trigger == "stage_start" and _opened(events, number):
        return round_json(ctx, session, problem)
    signals = read_signals(events, datetime.now(UTC))
    if trigger == "check_in" and (index is None or not should_check_in(signals)):
        return round_json(ctx, session, problem)
    code = _solution(ctx, session_id, problem)
    try:
        reply = interviewer_reply(
            ctx.anthropic_client,
            mock_model(),
            problem,
            session.stages,
            index,
            code,
            chat,
            trigger,
            style_of(session),
            signals,
        )
    except InterviewerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except anthropic.APIError as exc:
        raise HTTPException(
            status_code=502, detail=f"The interviewer could not reply: {exc.message}"
        ) from exc
    kind = MockEventKind.INTERVIEWER_MESSAGE
    event(ctx, session_id, kind, stage=number, text=reply, trigger=trigger)
    return round_json(ctx, session, problem)
