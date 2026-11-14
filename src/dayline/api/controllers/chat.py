"""HTTP controller for the LLM chat endpoints (analysis-first propose/confirm)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import chat as service

router = APIRouter()


class ChatRequest(BaseModel):
    day: str
    message: str
    history: list[dict[str, Any]] | None = None


@router.post("/api/chat")
def chat(body: ChatRequest, ctx: ContextDep) -> dict[str, Any]:
    """Analysis-first assistant. Never applies changes directly - see
    ``api/chat.py`` for the propose/confirm split. Proposals may be empty."""
    return service.run_chat(
        ctx, date.fromisoformat(body.day), body.message, body.history
    )


@router.post("/api/chat/stream")
def chat_stream(body: ChatRequest, ctx: ContextDep) -> StreamingResponse:
    """Streaming twin of ``POST /api/chat`` (SSE): status hints, token deltas,
    then one terminal ``done`` frame carrying the same payload.

    Deliberately a sync generator, like the other endpoints here - Starlette
    runs it in a threadpool, so the blocking Supabase/Anthropic calls never
    block the event loop.
    """
    return StreamingResponse(
        service.stream_chat(
            ctx, date.fromisoformat(body.day), body.message, body.history
        ),
        media_type="text/event-stream",
        headers={
            # ``no-transform`` is load-bearing, not boilerplate: without it the
            # Next dev proxy (and any gzip-ing reverse proxy) compresses the
            # stream and holds every frame until the turn ends.
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Tell nginx-style proxies not to buffer the stream.
            "X-Accel-Buffering": "no",
        },
    )


class ChatConfirmRequest(BaseModel):
    day: str
    proposals: list[dict[str, Any]]
    # Full set offered in the turn; anything not in ``proposals`` is logged rejected.
    offered: list[dict[str, Any]] | None = None


@router.post("/api/chat/confirm")
def chat_confirm(
    body: ChatConfirmRequest, ctx: ContextDep
) -> dict[str, Any]:
    """Apply the user-approved subset of a chat turn's proposals, log
    accept/reject outcomes, then re-plan the day."""
    return service.confirm_chat(
        ctx, date.fromisoformat(body.day), body.proposals, body.offered
    )
