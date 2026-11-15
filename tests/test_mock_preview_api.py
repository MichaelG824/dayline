"""Live previews of a session's dev servers: the signed-in server controls,
and the token-authenticated passthrough that serves the sandboxed app.

The real FastAPI app over in-memory sources and the in-memory sandbox fake.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dayline.adapters.mock_source import InMemoryMockSource
from dayline.adapters.sandbox import InMemorySandboxClient
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import SESSION_COOKIE, issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.api.services.mock_preview import SANDBOX_CSP, browser_headers, upstream_headers
from dayline.mock.templates import builtin_templates
from dayline.mock.worklog import timeline
from tests.mock_fakes import FakeAnthropic, FakeMessages, small_rubric

ALLOWED = "owner@example.com"


@pytest.fixture
def ctx() -> SimpleNamespace:
    return SimpleNamespace(
        task_source=InMemoryTaskSource(),
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


def _start(client: TestClient, template: str = "notes-board-next-nest") -> tuple[str, str]:
    res = client.post("/api/mock/live/sessions", json={"templateId": template})
    assert res.status_code == 201, res.text
    session_id = res.json()["id"]
    status = client.get(f"/api/mock/sessions/{session_id}/preview").json()
    return session_id, status["base"]


def test_a_session_gets_a_private_preview_base_and_its_servers(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    session_id, base = _start(client)
    assert base.startswith(f"/api/preview/{session_id}/") and len(base.rsplit("/", 1)[1]) >= 32
    assert ctx.sandbox.sandboxes[session_id]["previewBase"] == base
    status = client.get(f"/api/mock/sessions/{session_id}/preview").json()
    assert [(s["name"], s["port"], s["state"]) for s in status["servers"]] == [
        ("api", 4000, "ready"),
        ("web", 3000, "ready"),
    ]
    # A pack without dev servers has nothing to preview.
    res = client.post("/api/mock/live/sessions", json={"templateId": "rate-limiter"})
    other = client.get(f"/api/mock/sessions/{res.json()['id']}/preview").json()
    assert other["servers"] == []


def test_server_controls_and_logs_are_recorded(client: TestClient) -> None:
    session_id, _ = _start(client)
    res = client.post(f"/api/mock/sessions/{session_id}/servers/web/stop")
    assert {s["name"]: s["state"] for s in res.json()["servers"]}["web"] == "stopped"
    client.post(f"/api/mock/sessions/{session_id}/servers/web/restart")
    assert client.post(f"/api/mock/sessions/{session_id}/servers/web/explode").status_code == 400
    assert client.post(f"/api/mock/sessions/{session_id}/servers/nope/stop").status_code == 404
    logs = client.get(f"/api/mock/sessions/{session_id}/servers/web/logs?since=1").json()
    assert logs == {"lines": ["[dayline] stop", "[dayline] restart"], "next": 3, "truncated": False}
    res = client.post(f"/api/mock/sessions/{session_id}/preview/reloaded", json={"server": "web"})
    assert res.status_code == 204

    detail = client.get(f"/api/mock/sessions/{session_id}").json()
    kinds = [e["kind"] for e in detail["events"]]
    assert kinds.count("server_action") == 2 and "preview_reloaded" in kinds


def test_the_preview_needs_no_session_but_the_right_token(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    session_id, base = _start(client)
    client.cookies.clear()
    assert client.get(f"/api/mock/sessions/{session_id}/preview").status_code == 401
    res = client.get(f"{base}/3000")
    assert res.status_code == 200 and res.text == "<h1>Notes</h1>"
    assert res.headers["content-security-policy"] == SANDBOX_CSP

    wrong = base[:-4] + "AAAA"
    page = client.get(f"{wrong}/3000", headers={"Sec-Fetch-Dest": "iframe"})
    assert page.status_code == 404 and "The preview is not available" in page.text
    assert page.headers["content-security-policy"] == SANDBOX_CSP
    assert client.get(f"{wrong}/3000").json() == {"detail": "No such preview"}
    assert client.get(f"/api/preview/{session_id}/short/3000").status_code == 404
    assert client.get(f"{base}/5000/").status_code == 404
    assert len(ctx.sandbox.preview_requests) == 1


def test_requests_reach_the_app_as_if_made_inside_the_sandbox(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    _, base = _start(client)
    client.cookies.set("theme", "dark")
    res = client.post(
        f"{base}/3000/api/notes%2Fx?q=1",
        content=b'{"text": "hi"}',
        headers={
            "Content-Type": "application/json",
            "Origin": "null",
            "Referer": f"http://testserver{base}/3000/",
            "Sec-Fetch-Site": "cross-site",
            "X-Dayline-Preview-Base": "/spoofed",
        },
    )
    assert res.status_code == 200
    seen = ctx.sandbox.preview_requests[-1]
    assert (seen["method"], seen["path"], seen["query"], seen["body"]) == (
        "POST",
        "/api/notes%2Fx",
        "q=1",
        b'{"text": "hi"}',
    )
    headers = {k.lower(): v for k, v in seen["headers"]}
    assert headers["origin"] == "http://localhost:3000"
    assert headers["referer"] == f"http://localhost:3000{base}/3000/"
    # Browser cookies are Dayline's own (the session above all).
    assert "cookie" not in headers
    assert not any(k.startswith(("sec-fetch-", "x-dayline-")) for k in headers)
    # The root without a trailing slash stays distinct from "/".
    client.get(f"{base}/3000")
    assert ctx.sandbox.preview_requests[-1]["path"] == ""


def test_responses_are_made_safe_for_dayline_s_origin(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    _, base = _start(client)

    def reply(_request: dict[str, Any]) -> tuple[int, list[tuple[str, str]], bytes]:
        return (
            302,
            [
                ("Location", f"http://localhost:3000{base}/3000/notes"),
                ("Set-Cookie", "dayline_session=evil; Path=/"),
                ("Strict-Transport-Security", "max-age=31536000"),
                ("Clear-Site-Data", '"*"'),
                ("X-Frame-Options", "DENY"),
                ("Content-Type", "text/html"),
            ],
            b"",
        )

    ctx.sandbox.preview_reply = reply
    res = client.get(f"{base}/3000/new", headers={"Origin": "null"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == f"{base}/3000/notes"
    for header in ("set-cookie", "strict-transport-security", "clear-site-data", "x-frame-options"):
        assert header not in res.headers
    assert res.headers["access-control-allow-origin"] == "null"
    assert res.headers["referrer-policy"] == "no-referrer"


def test_cors_preflights_are_answered_without_the_app(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    _, base = _start(client)
    res = client.options(
        f"{base}/3000/api/notes",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 204
    assert res.headers["access-control-allow-origin"] == "null"
    assert res.headers["access-control-allow-methods"] == "POST"
    assert res.headers["access-control-allow-headers"] == "content-type"
    assert ctx.sandbox.preview_requests == []


def test_runner_refusals_become_an_error_page(client: TestClient, ctx: SimpleNamespace) -> None:
    _, base = _start(client)
    ctx.sandbox.preview_reply = lambda _r: (
        502,
        [("X-Dayline-Preview-Error", "1"), ("Content-Type", "application/json")],
        b'{"detail": "Nothing is answering on port 3000"}',
    )
    page = client.get(f"{base}/3000", headers={"Accept": "text/html"})
    assert page.status_code == 502 and "Nothing is answering on port 3000" in page.text
    assert "x-dayline-preview-error" not in page.headers


def test_websockets_are_bridged_with_the_app_s_subprotocol(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    _, base = _start(client)
    with client.websocket_connect(
        f"{base}/3000/_next/hmr?id=1", subprotocols=["hmr-v1"], headers={"Origin": "null"}
    ) as ws:
        assert ws.accepted_subprotocol == "hmr-v1"
        ws.send_text("ping")
        assert ws.receive_text() == "ping"
        ws.send_bytes(b"\x01")
        assert ws.receive_bytes() == b"\x01"
        # The app hangs up; so does the browser's socket.
        ws.send_text("close")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    socket = ctx.sandbox.preview_sockets[-1]
    assert socket.received[0].startswith("connect /_next/hmr")
    assert "http://localhost:3000" in socket.received[0]

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(base[:-4] + "AAAA/3000/"):
        pass


def test_header_rewriting_helpers() -> None:
    assert upstream_headers([("Accept", "text/html")], 4000) == [
        ("Accept", "text/html"),
        ("accept-encoding", "identity"),
    ]
    assert ("access-control-allow-origin", "*") in browser_headers([], None)


def test_preview_events_read_well_in_the_timeline() -> None:
    from datetime import UTC, datetime, timedelta

    from dayline.models import MockEvent, MockEventKind

    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        MockEvent(
            "s",
            MockEventKind.SERVER_ACTION,
            {"server": "web", "action": "restart"},
            at=start + timedelta(seconds=65),
        ),
        MockEvent(
            "s", MockEventKind.PREVIEW_RELOADED, {"server": "web"}, at=start + timedelta(seconds=70)
        ),
    ]
    assert timeline(events, start) == [
        "01:05 restarted the web dev server",
        "01:10 reloaded the web preview",
    ]


def test_built_in_full_stack_templates_stay_within_their_packs() -> None:
    from pathlib import Path

    from dayline_runner.deps import project_problems
    from dayline_runner.packs import load_packs

    packs = load_packs(Path(__file__).resolve().parents[1] / "sandbox" / "packs")
    for template in builtin_templates().values():
        manifest = packs[template.pack].dependencies
        if manifest is not None:
            assert project_problems(manifest, template.files) == [], template.id
