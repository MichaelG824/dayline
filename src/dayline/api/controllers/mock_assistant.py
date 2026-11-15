"""The coding assistant in AI-assisted live sessions: the conversation, a
streamed turn, cancelling it, and accepting or rejecting proposed edits.
Logic lives in ``services/mock_assistant.py``."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import mock_assistant as service

router = APIRouter()


class TurnRequest(BaseModel):
    mode: str
    prompt: str


class CancelRequest(BaseModel):
    turnId: str


class DecisionRequest(BaseModel):
    decision: Literal["accept", "reject"]


@router.get("/api/mock/sessions/{session_id}/assistant")
def state(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.state(ctx, session_id)


@router.post("/api/mock/sessions/{session_id}/assistant/turns")
def turn(session_id: str, body: TurnRequest, ctx: ContextDep) -> StreamingResponse:
    """One assistant turn as SSE (see ``service.start_turn`` for the frames).
    A sync generator, so Starlette runs the blocking model and sandbox calls
    in its threadpool."""
    stream = service.start_turn(ctx, session_id, body.mode, body.prompt)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        # no-transform keeps the Next dev proxy from gzipping (and so
        # buffering) the stream; see the chat stream endpoint.
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/mock/sessions/{session_id}/assistant/cancel", status_code=204)
def cancel(session_id: str, body: CancelRequest, ctx: ContextDep) -> Response:
    service.cancel(ctx, session_id, body.turnId)
    return Response(status_code=204)


@router.post("/api/mock/sessions/{session_id}/assistant/edits/{proposal_id}")
def decide(
    session_id: str, proposal_id: str, body: DecisionRequest, ctx: ContextDep
) -> dict[str, Any]:
    """Accept (write) or reject a proposed edit. Returns the edit with its
    new status: ``accepted``, ``rejected``, or ``conflict`` when the file
    changed since the edit was drafted (nothing is written then)."""
    return service.decide(ctx, session_id, proposal_id, body.decision == "accept")
