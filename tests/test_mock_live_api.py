"""Live mock sessions: start from a template, work in the sandbox (files,
tests, terminal), end, and grade the work record.

The real FastAPI app over in-memory sources and the in-memory sandbox fake,
signed in as the allowlisted account.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dayline.adapters.generated_source import InMemoryGeneratedProjectSource
from dayline.adapters.mock_source import InMemoryMockSource
from dayline.adapters.sandbox import InMemorySandboxClient
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import SESSION_COOKIE, issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.mock.templates import builtin_templates
from tests.mock_fakes import FakeAnthropic, FakeMessages, scorecard_payload, small_rubric

ALLOWED = "owner@example.com"
TEMPLATE = "library-late-fees"
SERVICE = "library/service.py"


@pytest.fixture
def ctx() -> SimpleNamespace:
    return SimpleNamespace(
        task_source=InMemoryTaskSource(),
        generated_source=InMemoryGeneratedProjectSource(),
        mock_source=InMemoryMockSource(rubrics=[small_rubric()]),
        anthropic_client=FakeAnthropic(FakeMessages([])),
        sandbox=InMemorySandboxClient(),
        client=None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, ctx: SimpleNamespace) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-not-for-production-use")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    app = create_app()
    app.dependency_overrides[get_context] = lambda: ctx
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE, issue_session(ALLOWED, ALLOWED))
        yield c


def _start(client: TestClient, **fields: Any) -> dict[str, Any]:
    res = client.post("/api/mock/live/sessions", json={"templateId": TEMPLATE, **fields})
    assert res.status_code == 201, res.text
    return dict(res.json())


def _event_kinds(client: TestClient, session_id: str) -> list[str]:
    return [e["kind"] for e in client.get(f"/api/mock/sessions/{session_id}").json()["events"]]


def test_availability_lists_templates_and_explains_a_missing_runner(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    live = client.get("/api/mock/live").json()
    assert live["available"] is True
    assert {t["id"] for t in live["templates"]} == set(builtin_templates())

    ctx.sandbox = None
    live = client.get("/api/mock/live").json()
    assert live["available"] is False and "SANDBOX_RUNNER_URL" in live["reason"]
    assert client.post("/api/mock/live/sessions", json={"templateId": TEMPLATE}).status_code == 503


def test_start_copies_the_template_into_a_sandbox(client: TestClient, ctx: SimpleNamespace) -> None:
    session = _start(client, rubricId="rubric-1")
    assert (session["kind"], session["status"], session["pack"]) == ("live", "live", "python")
    assert session["taskMd"].startswith("# Library checkout")
    assert session["durationMin"] == 45
    assert ctx.sandbox.sandboxes[session["id"]]["files"] == builtin_templates()[TEMPLATE].files
    assert _event_kinds(client, session["id"]) == ["session_started"]
    status = client.get(f"/api/mock/sessions/{session['id']}/sandbox").json()
    assert (status["state"], status["editorLanguage"]) == ("running", "python")


def test_bad_starts_leave_nothing_behind(client: TestClient, ctx: SimpleNamespace) -> None:
    assert client.post("/api/mock/live/sessions", json={"templateId": "nope"}).status_code == 404
    res = client.post("/api/mock/live/sessions", json={"templateId": TEMPLATE, "rubricId": "x"})
    assert res.status_code == 404
    ctx.sandbox.unavailable = True
    res = client.post("/api/mock/live/sessions", json={"templateId": TEMPLATE})
    assert res.status_code == 503 and "not reachable" in res.json()["detail"]
    assert client.get("/api/mock/sessions").json() == []


def test_saves_are_versioned_and_recorded(client: TestClient) -> None:
    sid = _start(client)["id"]
    files = client.get(f"/api/mock/sessions/{sid}/files").json()
    assert SERVICE in [f["path"] for f in files]

    opened = client.get(f"/api/mock/sessions/{sid}/files/{SERVICE}").json()
    fixed = opened["content"].replace(" and loan.member_id == member_id", "")
    url = f"/api/mock/sessions/{sid}/files/{SERVICE}"
    saved = client.put(url, json={"content": fixed, "baseVersion": opened["version"]})
    assert saved.status_code == 200 and saved.json()["version"] != opened["version"]

    # A save from an editor holding the old version is refused, not merged.
    stale = client.put(url, json={"content": "oops", "baseVersion": opened["version"]})
    assert stale.status_code == 409
    # Saving identical content records no event; a new file always does.
    client.put(url, json={"content": fixed})
    client.put(f"/api/mock/sessions/{sid}/files/notes.md", json={"content": "", "baseVersion": ""})

    events = client.get(f"/api/mock/sessions/{sid}").json()["events"]
    saves = [e["data"] for e in events if e["kind"] == "file_saved"]
    # Each save keeps its own diff, for the replay.
    assert "+            if loan.book_id == book_id and loan.is_open:" in saves[0].pop("diff")
    assert saves[1].pop("diff") == ""  # An empty new file has no lines to show.
    assert saves == [
        {"path": SERVICE, "added": 1, "removed": 1},
        {"path": "notes.md", "added": 0, "removed": 0},
    ]


def test_test_runs_are_kept_on_the_session(client: TestClient, ctx: SimpleNamespace) -> None:
    sid = _start(client)["id"]
    ctx.sandbox.next_report = {"status": "failed", "passed": 3, "failed": 5, "errors": 0}
    report = client.post(f"/api/mock/sessions/{sid}/tests").json()
    assert report["status"] == "failed"
    session = client.get(f"/api/mock/sessions/{sid}").json()
    assert session["testReport"]["failed"] == 5
    assert session["events"][-1] == {
        "kind": "tests_run",
        "data": {"status": "failed", "passed": 3, "failed": 5, "errors": 0},
        "at": session["events"][-1]["at"],
    }


def test_a_stopped_sandbox_can_be_resumed(client: TestClient, ctx: SimpleNamespace) -> None:
    sid = _start(client)["id"]
    ctx.sandbox.stop(sid)
    assert client.get(f"/api/mock/sessions/{sid}/sandbox").json()["state"] == "stopped"
    res = client.get(f"/api/mock/sessions/{sid}/files")
    assert res.status_code == 409 and res.json()["detail"] == "The sandbox is stopped"
    assert client.post(f"/api/mock/sessions/{sid}/resume").json()["state"] == "running"
    assert client.get(f"/api/mock/sessions/{sid}/files").status_code == 200


def test_ending_saves_the_diff_and_deletes_the_sandbox(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    url = f"/api/mock/sessions/{sid}/files/{SERVICE}"
    content = client.get(url).json()["content"]
    client.put(url, json={"content": content.replace("You already have this book", "Taken")})

    ended = client.post(f"/api/mock/sessions/{sid}/end").json()
    assert ended["status"] == "ended" and ended["endedAt"]
    assert '-                raise LibraryError("You already have this book")' in ended["finalDiff"]
    assert '+                raise LibraryError("Taken")' in ended["finalDiff"]
    assert sid not in ctx.sandbox.sandboxes
    assert _event_kinds(client, sid)[-1] == "session_ended"

    # Ending again is a no-op; the workspace is closed.
    assert client.post(f"/api/mock/sessions/{sid}/end").status_code == 200
    assert client.get(f"/api/mock/sessions/{sid}/files").status_code == 409
    assert client.get(f"/api/mock/sessions/{sid}/sandbox").status_code == 409


def test_terminal_commands_join_the_timeline_at_their_own_time(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    started = client.get(f"/api/mock/sessions/{sid}").json()["startedAt"]
    at = datetime.fromisoformat(started).timestamp()
    ctx.sandbox.sandboxes[sid]["commands"] += [
        {"at": at + 5, "exitCode": 1, "command": "pytest -q"},
        {"at": at + 9, "exitCode": 0, "command": "ls"},
    ]
    events = client.post(f"/api/mock/sessions/{sid}/end").json()["events"]

    commands = [e for e in events if e["kind"] == "command_run"]
    assert [c["data"] for c in commands] == [
        {"command": "pytest -q", "exitCode": 1},
        {"command": "ls", "exitCode": 0},
    ]
    assert [datetime.fromisoformat(c["at"]).timestamp() for c in commands] == [at + 5, at + 9]
    times = [datetime.fromisoformat(e["at"]) for e in events]
    assert times == sorted(times)


def test_a_lost_sandbox_still_ends_the_session(client: TestClient, ctx: SimpleNamespace) -> None:
    sid = _start(client)["id"]
    ctx.sandbox.sandboxes.pop(sid)
    assert client.get(f"/api/mock/sessions/{sid}/sandbox").json()["state"] == "gone"
    ended = client.post(f"/api/mock/sessions/{sid}/end").json()
    assert (ended["status"], ended["finalDiff"]) == ("ended", "")
    assert ended["events"][-1]["data"] == {"sandboxLost": True}


def test_an_unreachable_runner_does_not_end_the_session(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    ctx.sandbox.unavailable = True
    assert client.post(f"/api/mock/sessions/{sid}/end").status_code == 503
    assert client.get(f"/api/mock/sessions/{sid}").json()["status"] == "live"


def test_live_sessions_are_graded_on_the_work_record_once_ended(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client, rubricId="rubric-1")["id"]
    ctx.sandbox.next_report = {"status": "passed", "passed": 8, "failed": 0, "errors": 0}
    client.post(f"/api/mock/sessions/{sid}/tests")
    res = client.post(f"/api/mock/sessions/{sid}/grade")
    assert res.status_code == 409 and "End the session" in res.json()["detail"]

    client.post(f"/api/mock/sessions/{sid}/end")
    ctx.anthropic_client = FakeAnthropic.replying(("submit_scorecard", scorecard_payload()))
    graded = client.post(f"/api/mock/sessions/{sid}/grade").json()
    assert graded["scorecard"]["overallScore"] == 2.5
    prompt = ctx.anthropic_client.messages.calls[0]["messages"][0]["content"]
    assert "ran tests: passed (8 passed, 0 failed, 0 errors)" in prompt


def test_deleting_a_live_session_deletes_its_sandbox(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    assert client.delete(f"/api/mock/sessions/{sid}").status_code == 204
    assert sid not in ctx.sandbox.sandboxes


def _terminal_url(sid: str) -> str:
    return f"/api/mock/sessions/{sid}/terminal?cols=100&rows=30"


def test_terminal_relays_both_ways(client: TestClient, ctx: SimpleNamespace) -> None:
    sid = _start(client)["id"]
    with client.websocket_connect(_terminal_url(sid)) as ws:
        ws.send_bytes(b"ls\n")
        assert ws.receive_bytes() == b"ls\n"
        ws.send_text('{"type":"resize","cols":120,"rows":40}')
        ws.send_bytes(b"exit\n")
        closed = ws.receive()
    assert closed["type"] == "websocket.close" and closed["code"] == 1000
    assert ctx.sandbox.terminals[0].received[1] == '{"type":"resize","cols":120,"rows":40}'


@pytest.mark.parametrize(
    ("signed_in", "headers"),
    [(False, {}), (True, {"origin": "https://evil.example"})],
    ids=["no-session", "foreign-origin"],
)
def test_terminal_refuses_strangers(
    client: TestClient, signed_in: bool, headers: dict[str, str]
) -> None:
    sid = _start(client)["id"]
    if not signed_in:
        client.cookies.clear()
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        client.websocket_connect(_terminal_url(sid), headers=headers),
    ):
        pass
    assert refused.value.code == 1008


def test_terminal_of_an_ended_session_closes_with_the_reason(client: TestClient) -> None:
    sid = _start(client)["id"]
    client.post(f"/api/mock/sessions/{sid}/end")
    with client.websocket_connect(_terminal_url(sid)) as ws:
        closed = ws.receive()
    assert (closed["code"], closed["reason"]) == (4409, "This session has ended")
