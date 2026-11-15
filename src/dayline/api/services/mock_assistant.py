"""The coding assistant in AI-assisted live sessions (``mock/assistant.py``).

This module wires the assistant to the session's sandbox, streams a turn as
SSE frames, and records everything as session events: each prompt with its
mode, each reply with its tool calls and timings, each proposed edit with its
diff, and what the candidate decided about it. Accepting an edit writes the
proposed content through the live-session file path, and only if the file is
still at the version the edit was drafted against; otherwise the edit is
marked as a conflict and nothing is written.

The conversation is rebuilt from those events, so it survives restarts. A
turn in flight is tracked in memory (one at a time per session), which is
what cancelling acts on.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import anthropic
from fastapi import HTTPException

from dayline.adapters.sandbox import SandboxRequestError, SandboxUnavailable
from dayline.api.context import AppContext
from dayline.api.services.mock import _get_session, assistant_enabled
from dayline.api.services.mock_live import (
    event,
    live_session,
    runner_errors,
    sandbox_client,
    write_file,
)
from dayline.api.services.mock_preview import server_logs_reader
from dayline.mock import assistant_model
from dayline.mock.assistant import (
    MODES,
    Mode,
    PastTurn,
    Proposal,
    ToolError,
    TurnError,
    TurnResult,
    Workspace,
    stream_turn,
)
from dayline.models import MockEvent, MockEventKind, MockSession

MAX_PROMPT_CHARS = 8000
# A turn whose stream never started (the client left before the first frame)
# never frees its session; after this long its slot is taken as abandoned.
STALE_TURN_S = 15 * 60

# Turns in flight: session id -> (turn id, start), and the turn ids asked to
# stop. Guarded by ``_lock``.
_lock = threading.Lock()
_running: dict[str, tuple[str, float]] = {}
_cancelled: set[str] = set()


def _current_turn(session_id: str) -> str | None:
    """The session's turn in flight, if any. Call with ``_lock`` held."""
    entry = _running.get(session_id)
    if entry is None:
        return None
    turn_id, started = entry
    if time.monotonic() - started > STALE_TURN_S:
        del _running[session_id]
        return None
    return turn_id


def _release(session_id: str, turn_id: str) -> None:
    with _lock:
        if _running.get(session_id, ("", 0.0))[0] == turn_id:
            del _running[session_id]
        _cancelled.discard(turn_id)


def _session(ctx: AppContext, session_id: str) -> MockSession:
    """A live session that has the assistant, or a 404/409."""
    session = live_session(ctx, session_id)
    if not assistant_enabled(ctx, session):
        raise HTTPException(status_code=404, detail="This round has no AI assistant")
    return session


def _workspace(ctx: AppContext, session_id: str) -> Workspace:
    sandbox = sandbox_client(ctx)

    def read_file(path: str) -> dict[str, Any]:
        try:
            return sandbox.read_file(session_id, path)
        except SandboxRequestError as exc:
            # Missing, too large, or not text: the model can work around it.
            if exc.status_code in (400, 404, 413, 415, 422):
                raise ToolError(exc.detail) from exc
            raise

    return Workspace(
        list_files=lambda: sandbox.list_files(session_id),
        read_file=read_file,
        snapshot=lambda: dict(sandbox.snapshot(session_id)["files"]),
        test_report=lambda: _get_session(ctx, session_id).test_report,
        commands=lambda: sandbox.commands(session_id),
        server_logs=server_logs_reader(sandbox, session_id),
    )


# --------------------------------------------------------------------------- #
# The conversation, from events
# --------------------------------------------------------------------------- #


def _decision(decisions: list[MockEvent]) -> str:
    """A proposal's state: an accept is final, else the latest decision."""
    kinds = [str(d.data.get("decision")) for d in decisions]
    if "accepted" in kinds:
        return "accepted"
    return kinds[-1] if kinds else "pending"


def _proposal_json(proposed: MockEvent, decisions: list[MockEvent]) -> dict[str, Any]:
    d = proposed.data
    decided = decisions[-1].at if decisions else None
    return {
        "id": d.get("proposalId"),
        "path": d.get("path"),
        "summary": d.get("summary", ""),
        "diff": d.get("diff", ""),
        "added": d.get("added", 0),
        "removed": d.get("removed", 0),
        "newFile": d.get("newFile", False),
        "status": _decision(decisions),
        "decidedAt": decided.isoformat() if decided else None,
    }


def _turns(events: list[MockEvent], running: str | None) -> list[dict[str, Any]]:
    """Every turn, oldest first, for the client. ``running`` is the number
    (as a string) of the turn in flight, if any."""
    decisions: dict[str, list[MockEvent]] = {}
    proposals: dict[int, list[MockEvent]] = {}
    responses: dict[int, MockEvent] = {}
    prompts: list[MockEvent] = []
    for e in events:
        if e.kind is MockEventKind.ASSISTANT_PROMPT:
            prompts.append(e)
        elif e.kind is MockEventKind.ASSISTANT_RESPONSE:
            responses[int(e.data.get("turn") or 0)] = e
        elif e.kind is MockEventKind.ASSISTANT_EDIT_PROPOSED:
            proposals.setdefault(int(e.data.get("turn") or 0), []).append(e)
        elif e.kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
            decisions.setdefault(str(e.data.get("proposalId")), []).append(e)

    turns = []
    for prompt in prompts:
        number = int(prompt.data.get("turn") or 0)
        response = responses.get(number)
        r = response.data if response else {}
        if response is not None:
            status, error = r.get("status", "done"), r.get("error")
        elif running == str(number):
            status, error = "running", None
        else:
            status, error = "error", "This reply was interrupted."
        turns.append(
            {
                "turn": number,
                "mode": prompt.data.get("mode"),
                "prompt": prompt.data.get("text", ""),
                "reply": r.get("text", ""),
                "status": status,
                "error": error,
                "tools": r.get("tools", []),
                "durationMs": r.get("durationMs"),
                "at": prompt.at.isoformat() if prompt.at else None,
                "proposals": [
                    _proposal_json(p, decisions.get(str(p.data.get("proposalId")), []))
                    for p in proposals.get(number, [])
                ],
            }
        )
    return turns


def _history(turns: list[dict[str, Any]]) -> list[PastTurn]:
    """Finished turns, as the model is reminded of them."""
    return [
        PastTurn(
            mode=t["mode"],
            prompt=t["prompt"],
            reply=t["reply"],
            edits=[(p["path"], p["summary"], p["status"]) for p in t["proposals"]],
        )
        for t in turns
        if t["status"] in ("done", "cancelled") and t["mode"] in MODES
    ]


def state(ctx: AppContext, session_id: str) -> dict[str, Any]:
    _session(ctx, session_id)
    with _lock:
        running = _current_turn(session_id)
    events = ctx.mock_source.list_events(session_id)
    turns = _turns(events, running and running.split(":")[1])
    return {"model": assistant_model(), "turns": turns, "running": running is not None}


# --------------------------------------------------------------------------- #
# A turn
# --------------------------------------------------------------------------- #


def _frame(payload: dict[str, Any]) -> str:
    """One SSE frame (hand-formatted, like ``services/chat.py``)."""
    return f"data: {json.dumps(payload)}\n\n"


def _preview_json(proposal: Proposal) -> dict[str, Any]:
    added, removed = proposal.counts()
    return {
        "id": proposal.id,
        "path": proposal.path,
        "summary": proposal.summary,
        "diff": proposal.diff(),
        "added": added,
        "removed": removed,
        "newFile": proposal.new_file,
        "status": "pending",
        "decidedAt": None,
    }


def _error_message(exc: Exception) -> str:
    if isinstance(exc, anthropic.RateLimitError):
        return "The assistant is rate limited right now. Try again in a minute."
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code in (500, 502, 503, 529):
        return "The assistant's model is overloaded right now. Try again."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the assistant's model. Try again."
    if isinstance(exc, anthropic.APIError):
        return f"The assistant failed: {exc.message}"
    if isinstance(exc, TurnError | SandboxUnavailable | SandboxRequestError):
        return str(exc)
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return "The assistant failed unexpectedly. Try again."


def start_turn(ctx: AppContext, session_id: str, mode: str, prompt: str) -> Iterator[str]:
    """Check the request and record the prompt (raising HTTPException), then
    return the SSE stream of the reply. Frames: ``start`` (turn id, for
    cancelling), ``delta``, ``status``, ``tool``, ``proposal``, and last
    ``done`` or ``error``, both carrying the recorded turn."""
    _session(ctx, session_id)
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")
    text = prompt.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Write a prompt first")
    if len(text) > MAX_PROMPT_CHARS:
        raise HTTPException(
            status_code=400, detail=f"Keep prompts under {MAX_PROMPT_CHARS} characters"
        )
    workspace = _workspace(ctx, session_id)
    events = ctx.mock_source.list_events(session_id)
    turns = _turns(events, None)
    number = max((t["turn"] for t in turns), default=0) + 1
    turn_id = f"{uuid.uuid4()}:{number}"
    with _lock:
        if _current_turn(session_id) is not None:
            raise HTTPException(
                status_code=409, detail="The assistant is still answering. Stop it or wait."
            )
        _running[session_id] = (turn_id, time.monotonic())
    try:
        event(ctx, session_id, MockEventKind.ASSISTANT_PROMPT, turn=number, mode=mode, text=text)
    except Exception:
        _release(session_id, turn_id)
        raise
    return _run_turn(
        ctx, session_id, workspace, turn_id, number, mode, text, _history(turns)
    )


def _run_turn(
    ctx: AppContext,
    session_id: str,
    workspace: Workspace,
    turn_id: str,
    number: int,
    mode: Mode,
    prompt: str,
    history: list[PastTurn],
) -> Iterator[str]:
    started = time.monotonic()
    first_token_ms: int | None = None
    parts: list[str] = []
    tools: list[str] = []
    drafts: dict[str, Proposal] = {}
    result: TurnResult | None = None
    error: str | None = None
    closed = False
    turn = stream_turn(
        ctx.anthropic_client,
        assistant_model(),
        mode,
        history,
        prompt,
        workspace,
        cancelled=lambda: turn_id in _cancelled,
    )
    try:
        yield _frame({"type": "start", "turnId": turn_id, "turn": number})
        for kind, value in turn:
            if kind == "delta":
                if first_token_ms is None:
                    first_token_ms = int((time.monotonic() - started) * 1000)
                parts.append(value)
                yield _frame({"type": "delta", "text": value})
            elif kind == "status":
                yield _frame({"type": "status", "message": value})
            elif kind == "tool":
                tools.append(value)
                yield _frame({"type": "tool", "summary": value})
            elif kind == "proposal":
                drafts[value.path] = value
                yield _frame({"type": "proposal", "proposal": _preview_json(value)})
            elif kind == "result":
                result = value
    except GeneratorExit:
        # The client went away (closed the tab, or aborted the request).
        closed = True
    except Exception as exc:  # noqa: BLE001 - a terminal frame beats a dead stream
        error = _error_message(exc)
    finally:
        turn.close()
        if result is None:
            result = TurnResult(
                text="".join(parts).strip(),
                tools=tools,
                proposals=list(drafts.values()),
                status="cancelled" if closed else "error",
                error=None if closed else error,
            )
        try:
            _record(ctx, session_id, number, mode, result, started, first_token_ms)
        finally:
            _release(session_id, turn_id)
    if closed:
        return
    events = ctx.mock_source.list_events(session_id)
    recorded = next(t for t in _turns(events, None) if t["turn"] == number)
    if result.status == "error":
        yield _frame({"type": "error", "message": result.error, "turn": recorded})
    else:
        yield _frame({"type": "done", "turn": recorded})


def _record(
    ctx: AppContext,
    session_id: str,
    number: int,
    mode: Mode,
    result: TurnResult,
    started: float,
    first_token_ms: int | None,
) -> None:
    """The turn's proposals, then its response, as events. Proposals are
    recorded even when the turn was stopped or failed, so they can still be
    reviewed."""
    for proposal in result.proposals:
        added, removed = proposal.counts()
        event(
            ctx,
            session_id,
            MockEventKind.ASSISTANT_EDIT_PROPOSED,
            turn=number,
            proposalId=proposal.id,
            path=proposal.path,
            summary=proposal.summary,
            baseVersion=proposal.base_version,
            newFile=proposal.new_file,
            content=proposal.content,
            diff=proposal.diff(),
            added=added,
            removed=removed,
        )
    data: dict[str, Any] = {
        "turn": number,
        "mode": mode,
        "text": result.text,
        "tools": result.tools,
        "proposals": [p.id for p in result.proposals],
        "status": result.status,
        "durationMs": int((time.monotonic() - started) * 1000),
    }
    if first_token_ms is not None:
        data["firstTokenMs"] = first_token_ms
    if result.error:
        data["error"] = result.error
    event(ctx, session_id, MockEventKind.ASSISTANT_RESPONSE, **data)


def cancel(ctx: AppContext, session_id: str, turn_id: str) -> None:
    """Stop the turn in flight, if it is still ``turn_id``. Whatever was
    written so far is kept, marked as stopped."""
    _session(ctx, session_id)
    with _lock:
        if _current_turn(session_id) == turn_id:
            _cancelled.add(turn_id)


# --------------------------------------------------------------------------- #
# Reviewing an edit
# --------------------------------------------------------------------------- #


def decide(ctx: AppContext, session_id: str, proposal_id: str, accept: bool) -> dict[str, Any]:
    """Accept (write) or reject a proposed edit. An edit whose file changed
    since it was drafted is not written: it is marked ``conflict``."""
    _session(ctx, session_id)
    events = ctx.mock_source.list_events(session_id)
    proposed = next(
        (
            e
            for e in events
            if e.kind is MockEventKind.ASSISTANT_EDIT_PROPOSED
            and e.data.get("proposalId") == proposal_id
        ),
        None,
    )
    if proposed is None:
        raise HTTPException(status_code=404, detail="No such proposed edit")
    decisions = [
        e
        for e in events
        if e.kind is MockEventKind.ASSISTANT_EDIT_DECIDED
        and e.data.get("proposalId") == proposal_id
    ]
    current = _decision(decisions)
    if current in ("accepted", "rejected"):
        raise HTTPException(status_code=409, detail=f"This edit was already {current}")

    path = str(proposed.data["path"])
    decision = "accepted" if accept else "rejected"
    if accept:
        base = str(proposed.data.get("baseVersion") or "")
        if _version(ctx, session_id, path) != base:
            decision = "conflict"
        else:
            try:
                write_file(ctx, session_id, path, str(proposed.data["content"]), base)
            except HTTPException as exc:
                if exc.status_code != 409 or "changed" not in str(exc.detail):
                    raise
                decision = "conflict"

    now = datetime.now(UTC)
    review_ms = int((now - proposed.at).total_seconds() * 1000) if proposed.at else None
    decided = MockEvent(
        session_id=session_id,
        kind=MockEventKind.ASSISTANT_EDIT_DECIDED,
        data={"proposalId": proposal_id, "path": path, "decision": decision, "reviewMs": review_ms},
    )
    stored = ctx.mock_source.add_event(decided)
    return _proposal_json(proposed, [*decisions, stored])


def _version(ctx: AppContext, session_id: str, path: str) -> str:
    """The file's version now, or ``""`` if it does not exist."""
    with runner_errors():
        try:
            return str(sandbox_client(ctx).read_file(session_id, path)["version"])
        except SandboxRequestError as exc:
            if exc.status_code != 404:
                raise
            return ""
