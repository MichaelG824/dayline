"""The in-session assistant through the API: who gets it, a streamed turn
and what it records, accepting (writes exactly the proposed content),
rejecting (writes nothing), conflicts, errors, and the grader's record.

The real FastAPI app over in-memory sources, the in-memory sandbox fake, and
a scripted Anthropic client, signed in as the allowlisted account.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from dayline.adapters.mock_source import InMemoryMockSource
from dayline.adapters.sandbox import InMemorySandboxClient
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import SESSION_COOKIE, issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.api.services import mock_assistant
from dayline.mock import DEFAULT_ASSISTANT_MODEL
from dayline.mock.templates import builtin_templates
from dayline.mock.worklog import work_record
from tests.mock_fakes import FakeAnthropic, FakeMessages, FakeResponse, FakeText, FakeToolUse

ALLOWED = "owner@example.com"
TEMPLATE = "library-late-fees"
SERVICE = "library/service.py"
ORIGINAL = builtin_templates()[TEMPLATE].files[SERVICE]
OLD = "LOAN_DAYS = 14"
NEW = "LOAN_DAYS = 21"


@pytest.fixture
def messages() -> FakeMessages:
    return FakeMessages([])


@pytest.fixture
def ctx(messages: FakeMessages) -> SimpleNamespace:
    return SimpleNamespace(
        task_source=InMemoryTaskSource(),
        mock_source=InMemoryMockSource(),
        anthropic_client=FakeAnthropic(messages),
        sandbox=InMemorySandboxClient(),
        client=None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, ctx: SimpleNamespace) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-not-for-production-use")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.delenv("MOCK_ASSISTANT_MODEL", raising=False)
    app = create_app()
    app.dependency_overrides[get_context] = lambda: ctx
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE, issue_session(ALLOWED, ALLOWED))
        yield c


def _start(client: TestClient) -> str:
    res = client.post("/api/mock/live/sessions", json={"templateId": TEMPLATE})
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def _turn(client: TestClient, session_id: str, mode: str, prompt: str) -> list[dict[str, Any]]:
    """Send a prompt; the SSE frames of the reply."""
    res = client.post(
        f"/api/mock/sessions/{session_id}/assistant/turns", json={"mode": mode, "prompt": prompt}
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in res.headers["cache-control"]
    return [json.loads(f.removeprefix("data: ")) for f in res.text.split("\n\n") if f.strip()]


def _edit_reply(messages: FakeMessages, path: str = SERVICE, **edit: Any) -> None:
    payload = {"path": path, "summary": "Longer loans.", **edit}
    if "edits" not in payload and "new_content" not in payload:
        payload["edits"] = [{"old_text": OLD, "new_text": NEW}]
    messages.responses += [
        FakeResponse([FakeToolUse("propose_edit", payload)]),
        FakeResponse([FakeText("Changed the loan period.")]),
    ]


def _decide(client: TestClient, session_id: str, proposal_id: str, decision: str) -> Any:
    return client.post(
        f"/api/mock/sessions/{session_id}/assistant/edits/{proposal_id}",
        json={"decision": decision},
    )


def _events(ctx: SimpleNamespace, session_id: str, kind: str) -> list[dict[str, Any]]:
    return [dict(e.data) for e in ctx.mock_source.list_events(session_id) if e.kind == kind]


def _files(ctx: SimpleNamespace, session_id: str) -> dict[str, str]:
    files: dict[str, str] = ctx.sandbox.sandboxes[session_id]["files"]
    return files


# --------------------------------------------------------------------------- #
# Who gets it
# --------------------------------------------------------------------------- #


def test_ai_assisted_live_rounds_have_the_assistant(client: TestClient) -> None:
    session_id = _start(client)
    assert client.get(f"/api/mock/sessions/{session_id}").json()["assistant"] is True
    state = client.get(f"/api/mock/sessions/{session_id}/assistant").json()
    assert state == {"model": DEFAULT_ASSISTANT_MODEL, "turns": [], "running": False}


def test_staged_rounds_and_ended_sessions_do_not(client: TestClient) -> None:
    res = client.post("/api/mock/staged/sessions", json={"problemId": "lru-cache"})
    staged_id = res.json()["id"]
    assert client.get(f"/api/mock/sessions/{staged_id}").json()["assistant"] is False
    assert client.get(f"/api/mock/sessions/{staged_id}/assistant").status_code == 404
    res = client.post(
        f"/api/mock/sessions/{staged_id}/assistant/turns", json={"mode": "ask", "prompt": "hi"}
    )
    assert res.status_code == 404

    session_id = _start(client)
    client.post(f"/api/mock/sessions/{session_id}/end")
    assert client.get(f"/api/mock/sessions/{session_id}/assistant").status_code == 409


def test_bad_prompts_are_refused_before_anything_is_recorded(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    session_id = _start(client)
    url = f"/api/mock/sessions/{session_id}/assistant/turns"
    assert client.post(url, json={"mode": "write", "prompt": "hi"}).status_code == 400
    assert client.post(url, json={"mode": "ask", "prompt": "  "}).status_code == 400
    assert client.post(url, json={"mode": "ask", "prompt": "x" * 9000}).status_code == 400
    assert _events(ctx, session_id, "assistant_prompt") == []


# --------------------------------------------------------------------------- #
# A turn
# --------------------------------------------------------------------------- #


def test_an_ask_turn_streams_and_is_recorded(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    messages.responses += [
        FakeResponse([FakeToolUse("read_file", {"path": SERVICE})]),
        FakeResponse([FakeText("Loans last 14 days.")]),
    ]

    frames = _turn(client, session_id, "ask", "How long are loans?")

    assert frames[0]["type"] == "start" and frames[0]["turn"] == 1
    assert {"type": "status", "message": "Reading code…"} in frames
    assert {"type": "tool", "summary": f"read {SERVICE}"} in frames
    assert "".join(f["text"] for f in frames if f["type"] == "delta") == "Loans last 14 days."
    done = frames[-1]
    assert done["type"] == "done"
    assert done["turn"]["reply"] == "Loans last 14 days."
    assert done["turn"]["status"] == "done" and done["turn"]["mode"] == "ask"
    assert messages.calls[0]["model"] == DEFAULT_ASSISTANT_MODEL

    (prompt,) = _events(ctx, session_id, "assistant_prompt")
    assert prompt == {"turn": 1, "mode": "ask", "text": "How long are loans?"}
    (response,) = _events(ctx, session_id, "assistant_response")
    assert response["text"] == "Loans last 14 days."
    assert response["tools"] == [f"read {SERVICE}"]
    assert response["status"] == "done" and response["proposals"] == []
    assert response["durationMs"] >= 0 and response["firstTokenMs"] >= 0

    state = client.get(f"/api/mock/sessions/{session_id}/assistant").json()
    assert state["turns"] == [done["turn"]]


def test_the_model_is_a_setting(
    client: TestClient, messages: FakeMessages, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_ASSISTANT_MODEL", "claude-sonnet-5-5")
    session_id = _start(client)
    messages.responses.append(FakeResponse([FakeText("hi")]))
    _turn(client, session_id, "ask", "hi")
    assert messages.calls[0]["model"] == "claude-sonnet-5-5"


def test_later_turns_remember_earlier_ones(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    _edit_reply(messages)
    proposal = _turn(client, session_id, "edit", "Make loans 21 days")[-1]["turn"]["proposals"][0]
    _decide(client, session_id, proposal["id"], "reject")
    messages.responses.append(FakeResponse([FakeText("Sure.")]))

    frames = _turn(client, session_id, "plan", "What next?")

    assert frames[0]["turn"] == 2
    sent = messages.calls[-1]["messages"]
    assert sent[0] == {"role": "user", "content": "[edit mode] Make loans 21 days"}
    assert f"{SERVICE}: rejected" in sent[1]["content"]
    assert sent[-1] == {"role": "user", "content": "[plan mode] What next?"}


def test_a_failed_model_call_ends_with_an_error_frame_and_can_be_retried(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    overloaded = anthropic.APIStatusError(
        "Overloaded", response=httpx.Response(529, request=request), body=None
    )
    messages.responses.append(overloaded)

    frames = _turn(client, session_id, "ask", "hi")

    assert frames[-1]["type"] == "error"
    assert "overloaded" in frames[-1]["message"]
    assert frames[-1]["turn"]["status"] == "error"
    (response,) = _events(ctx, session_id, "assistant_response")
    assert response["status"] == "error" and "overloaded" in response["error"]
    # The session is free for the retry.
    messages.responses.append(FakeResponse([FakeText("Hello.")]))
    assert _turn(client, session_id, "ask", "hi")[-1]["type"] == "done"


def test_one_turn_at_a_time_and_cancel_only_hits_the_running_turn(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    session_id = _start(client)
    mock_assistant._running[session_id] = "other:1"
    try:
        res = client.post(
            f"/api/mock/sessions/{session_id}/assistant/turns", json={"mode": "ask", "prompt": "x"}
        )
        assert res.status_code == 409
        url = f"/api/mock/sessions/{session_id}/assistant/cancel"
        assert client.post(url, json={"turnId": "stale:0"}).status_code == 204
        assert "stale:0" not in mock_assistant._cancelled
        assert client.post(url, json={"turnId": "other:1"}).status_code == 204
        assert "other:1" in mock_assistant._cancelled
        assert client.get(f"/api/mock/sessions/{session_id}/assistant").json()["running"]
    finally:
        mock_assistant._running.pop(session_id, None)
        mock_assistant._cancelled.discard("other:1")


def test_cancelling_keeps_the_partial_reply_marked_as_stopped(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)

    def cancel_on_second_word(event: Any) -> None:
        if event.type == "content_block_delta" and event.delta.text == "two ":
            mock_assistant._cancelled.add(mock_assistant._running[session_id])

    messages.before_event = cancel_on_second_word
    messages.responses.append(FakeResponse([FakeText("one two three")]))

    frames = _turn(client, session_id, "ask", "count")

    assert frames[-1]["type"] == "done"
    assert frames[-1]["turn"]["status"] == "cancelled"
    assert frames[-1]["turn"]["reply"] == "one"
    assert mock_assistant._cancelled == set() and session_id not in mock_assistant._running


# --------------------------------------------------------------------------- #
# Reviewing edits
# --------------------------------------------------------------------------- #


def test_ask_mode_cannot_change_files(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    before = dict(_files(ctx, session_id))
    _edit_reply(messages)

    frames = _turn(client, session_id, "ask", "Make loans 21 days")

    assert not [f for f in frames if f["type"] == "proposal"]
    assert frames[-1]["turn"]["proposals"] == []
    assert _files(ctx, session_id) == before
    assert _events(ctx, session_id, "assistant_edit_proposed") == []
    assert _events(ctx, session_id, "file_saved") == []


def test_accepting_writes_exactly_the_proposed_content(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    _edit_reply(messages)

    frames = _turn(client, session_id, "edit", "Make loans 21 days")

    (streamed,) = [f["proposal"] for f in frames if f["type"] == "proposal"]
    (proposal,) = frames[-1]["turn"]["proposals"]
    assert proposal == streamed
    assert proposal["status"] == "pending" and proposal["path"] == SERVICE
    assert (proposal["added"], proposal["removed"]) == (1, 1)
    assert f"-{OLD}" in proposal["diff"] and f"+{NEW}" in proposal["diff"]
    # Proposing wrote nothing.
    assert _files(ctx, session_id)[SERVICE] == ORIGINAL

    res = _decide(client, session_id, proposal["id"], "accept")

    assert res.status_code == 200 and res.json()["status"] == "accepted"
    assert _files(ctx, session_id)[SERVICE] == ORIGINAL.replace(OLD, NEW)
    (saved,) = _events(ctx, session_id, "file_saved")
    assert saved == {"path": SERVICE, "added": 1, "removed": 1}
    (decided,) = _events(ctx, session_id, "assistant_edit_decided")
    assert decided["decision"] == "accepted" and decided["reviewMs"] >= 0
    (recorded,) = _events(ctx, session_id, "assistant_edit_proposed")
    assert recorded["content"] == ORIGINAL.replace(OLD, NEW)
    assert recorded["turn"] == 1 and recorded["baseVersion"]
    # Decided once.
    assert _decide(client, session_id, proposal["id"], "reject").status_code == 409
    # The session's event list leaves the full content out.
    detail = client.get(f"/api/mock/sessions/{session_id}").json()
    (event,) = [e for e in detail["events"] if e["kind"] == "assistant_edit_proposed"]
    assert "content" not in event["data"] and event["data"]["diff"]


def test_rejecting_writes_nothing(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    before = dict(_files(ctx, session_id))
    _edit_reply(messages)
    (proposal,) = _turn(client, session_id, "edit", "Make loans 21 days")[-1]["turn"]["proposals"]

    res = _decide(client, session_id, proposal["id"], "reject")

    assert res.json()["status"] == "rejected"
    assert _files(ctx, session_id) == before
    assert _events(ctx, session_id, "file_saved") == []
    assert _decide(client, session_id, proposal["id"], "accept").status_code == 409
    assert _files(ctx, session_id) == before


def test_a_file_changed_since_the_proposal_is_a_conflict_not_a_clobber(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    _edit_reply(messages)
    (proposal,) = _turn(client, session_id, "edit", "Make loans 21 days")[-1]["turn"]["proposals"]
    mine = ORIGINAL + "\n# my own change\n"
    client.put(f"/api/mock/sessions/{session_id}/files/{SERVICE}", json={"content": mine})

    res = _decide(client, session_id, proposal["id"], "accept")

    assert res.status_code == 200 and res.json()["status"] == "conflict"
    assert _files(ctx, session_id)[SERVICE] == mine
    (decided,) = _events(ctx, session_id, "assistant_edit_decided")
    assert decided["decision"] == "conflict"
    # It can still be dismissed.
    assert _decide(client, session_id, proposal["id"], "reject").json()["status"] == "rejected"
    assert _files(ctx, session_id)[SERVICE] == mine


def test_a_runner_side_conflict_is_caught_too(
    client: TestClient,
    ctx: SimpleNamespace,
    messages: FakeMessages,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The version check and the write are separate calls; the runner's own
    check catches a change in between."""
    session_id = _start(client)
    _edit_reply(messages)
    (proposal,) = _turn(client, session_id, "edit", "Make loans 21 days")[-1]["turn"]["proposals"]
    sandbox = ctx.sandbox
    real_write = sandbox.write_file

    def racing_write(sid: str, path: str, content: str, base: str | None) -> dict[str, Any]:
        sandbox.sandboxes[sid]["files"][path] = "raced\n"
        return real_write(sid, path, content, base)

    monkeypatch.setattr(sandbox, "write_file", racing_write)
    assert _decide(client, session_id, proposal["id"], "accept").json()["status"] == "conflict"
    assert _files(ctx, session_id)[SERVICE] == "raced\n"


def test_new_files_are_created_and_conflict_if_created_meanwhile(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    _edit_reply(messages, path="library/fees.py", new_content="RATE = 25\n")
    _edit_reply(messages, path="library/other.py", new_content="X = 1\n")
    (first,) = _turn(client, session_id, "edit", "Add fees")[-1]["turn"]["proposals"]
    (second,) = _turn(client, session_id, "edit", "Add other")[-1]["turn"]["proposals"]
    assert first["newFile"] is True
    client.put(f"/api/mock/sessions/{session_id}/files/library/other.py", json={"content": "Y\n"})

    assert _decide(client, session_id, first["id"], "accept").json()["status"] == "accepted"
    assert _decide(client, session_id, second["id"], "accept").json()["status"] == "conflict"
    assert _files(ctx, session_id)["library/fees.py"] == "RATE = 25\n"
    assert _files(ctx, session_id)["library/other.py"] == "Y\n"


def test_unknown_edits_404(client: TestClient) -> None:
    session_id = _start(client)
    assert _decide(client, session_id, "nope", "accept").status_code == 404


# --------------------------------------------------------------------------- #
# The grader's record
# --------------------------------------------------------------------------- #


def test_the_work_record_has_a_compact_ai_log(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session_id = _start(client)
    messages.responses.append(FakeResponse([FakeText("Step 1: change LOAN_DAYS.")]))
    _turn(client, session_id, "plan", "How do I make loans 21 days?")
    _edit_reply(messages)
    (proposal,) = _turn(client, session_id, "edit", "Do it")[-1]["turn"]["proposals"]
    _decide(client, session_id, proposal["id"], "accept")
    _edit_reply(messages, path="library/fees.py", new_content="RATE = 25\n")
    _turn(client, session_id, "edit", "Add a fee rate")
    client.post(f"/api/mock/sessions/{session_id}/end")

    session = ctx.mock_source.get_session(session_id)
    record = work_record(session, ctx.mock_source.list_events(session_id))

    assert "## AI assistant use" in record
    assert (
        "3 prompts (ask 0, plan 1, edit 2); 2 edits proposed: 1 accepted, 0 rejected, "
        "0 conflicted with the candidate's own changes, 1 never reviewed." in record
    )
    assert "plan mode, reply in" in record
    assert "Prompt: How do I make loans 21 days?" in record
    assert f"Looked at: proposed an edit to {SERVICE} (+1 -1)" in record
    assert f"Proposed edit to {SERVICE} (+1 -1): Longer loans. -> accepted after" in record
    assert "Proposed new file library/fees.py (+1 -0): Longer loans. -> never reviewed" in record
    assert 'asked the AI assistant (plan mode): "How do I make loans 21 days?"' in record
    assert f"accepted the AI assistant's edit to {SERVICE}" in record
    # A proposal's content stays out of the record (and this one was never applied).
    assert "RATE = 25" not in record
