"""Staged rounds: a live session whose interviewer adds production follow-ups
to the candidate's own code, stage by stage (see ``mock/staged.py``).

The round runs in an ordinary live-session sandbox, so files, the terminal,
resuming, and ending go through ``services/mock_live.py``. This module adds
what is staged about it: hidden test runs that gate each stage, skipping, and
the interviewer's turns. The stage state lives on the session
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
from dayline.mock import mock_model, staged
from dayline.mock.interviewer import ChatMessage, InterviewerError, Trigger, interviewer_reply
from dayline.mock.staged import StagedProblem
from dayline.models import (
    MockEvent,
    MockEventKind,
    MockSession,
    MockSessionKind,
    MockSessionStatus,
    StageStatus,
)

MAX_MESSAGE_CHARS = 4000


def problem_of(session: MockSession) -> StagedProblem:
    problem = staged.builtin_staged_problems().get(session.staged_problem_id or "")
    if problem is None:
        raise HTTPException(
            status_code=410, detail=f"The staged problem {session.staged_problem_id!r} is gone"
        )
    return problem


def _staged_session(ctx: AppContext, session_id: str) -> tuple[MockSession, StagedProblem]:
    """A staged round still in progress, or a 404/409."""
    session = live_session(ctx, session_id)
    if not session.staged_problem_id:
        raise HTTPException(status_code=404, detail="Not a staged round")
    return session, problem_of(session)


def round_json(ctx: AppContext, session: MockSession, problem: StagedProblem) -> dict[str, Any]:
    events = ctx.mock_source.list_events(session.id)
    return staged_round_json(problem, session, events, datetime.now(UTC))


def start_round(
    ctx: AppContext,
    problem_id: str,
    question_id: str | None,
    rubric_id: str | None,
    guideline_id: str | None,
) -> str:
    """Create the session and its sandbox with stage 1 active; returns the
    session id. If the sandbox cannot start, the session is not kept."""
    sandbox = sandbox_client(ctx)
    problem = staged.builtin_staged_problems().get(problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail=f"No staged problem {problem_id!r}")
    check_session_refs(ctx, question_id, rubric_id, guideline_id)

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
    event(ctx, session.id, MockEventKind.SESSION_STARTED, stagedProblem=problem.id)
    return session.id


def _solution(ctx: AppContext, session_id: str, problem: StagedProblem) -> dict[str, str]:
    """The candidate's solution files as they are in the sandbox now."""
    with runner_errors():
        files: dict[str, str] = sandbox_client(ctx).snapshot(session_id)["files"]
    return staged.solution_files(problem, files)


def _active(session: MockSession) -> int:
    index = staged.active_index(session.stages)
    if index is None:
        raise HTTPException(status_code=409, detail="Every stage is done. End the round.")
    return index


def run_stage_tests(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Run the active stage's hidden tests (plus every passed stage's). A
    passing run finishes the stage and unlocks the next one."""
    session, problem = _staged_session(ctx, session_id)
    index = _active(session)
    with runner_errors():
        report = sandbox_client(ctx).run_hidden_tests(
            session_id, staged.hidden_files(problem, session.stages)
        )
    passed = staged.record_run(problem, session.stages, report)
    number = index + 1
    event(
        ctx,
        session_id,
        MockEventKind.STAGE_TESTS_RUN,
        stage=number,
        status=report.get("status"),
        passed=report.get("passed", 0),
        failed=report.get("failed", 0),
        errors=report.get("errors", 0),
    )
    if passed:
        code = _solution(ctx, session_id, problem)
        staged.finish_stage(session.stages, StageStatus.PASSED, code, datetime.now(UTC))
        event(ctx, session_id, MockEventKind.STAGE_PASSED, stage=number)
    session.test_report = report
    ctx.mock_source.update_session(session)
    return {"report": report, "passed": passed, "staged": round_json(ctx, session, problem)}


def skip_stage(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Move on without passing the active stage; recorded as skipped."""
    session, problem = _staged_session(ctx, session_id)
    index = _active(session)
    code = _solution(ctx, session_id, problem)
    staged.finish_stage(session.stages, StageStatus.SKIPPED, code, datetime.now(UTC))
    ctx.mock_source.update_session(session)
    event(ctx, session_id, MockEventKind.STAGE_SKIPPED, stage=index + 1)
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
    """One interviewer reply. ``stage_start`` opens the active stage (or
    closes the round once every stage is done) and happens once per stage, so
    a reload never repeats it; ``follow_up`` asks the next question;
    ``message`` records the candidate's message first, then replies to it.
    The candidate's message is kept even if the reply fails, and ``message``
    with no text retries the reply to it."""
    session, problem = _staged_session(ctx, session_id)
    index = staged.active_index(session.stages)
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
