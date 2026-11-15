"""Staged rounds: start one, run the active stage's hidden tests, skip a
stage, and talk to the interviewer. Files, the terminal, and ending use the
live-session routes (``controllers/mock_live.py``). Logic lives in
``services/mock_staged.py``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import mock as mock_service
from dayline.api.services import mock_staged as service
from dayline.mock.interviewer import Trigger

router = APIRouter()


class StartRequest(BaseModel):
    problemId: str
    rubricId: str | None = None
    guidelineId: str | None = None


class InterviewerRequest(BaseModel):
    trigger: Trigger
    # The candidate's message; required when trigger is "message".
    message: str | None = None


@router.post("/api/mock/staged/sessions", status_code=201)
def start_round(body: StartRequest, ctx: ContextDep) -> dict[str, Any]:
    session_id = service.start_round(ctx, body.problemId, body.rubricId, body.guidelineId)
    return mock_service.get_session(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/stage/tests")
def run_stage_tests(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    """Run the active stage's hidden tests. Slow: up to the pack's test timeout."""
    return service.run_stage_tests(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/stage/skip")
def skip_stage(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.skip_stage(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/interviewer")
def interviewer_turn(session_id: str, body: InterviewerRequest, ctx: ContextDep) -> dict[str, Any]:
    """One interviewer reply (a model call): returns the round with the chat."""
    return service.interviewer_turn(ctx, session_id, body.trigger, body.message)
