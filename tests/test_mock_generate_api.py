"""Generated projects through the API: generate in the background and follow
it, the one-at-a-time cap, input limits, cancel, what the client may see,
preview, start a round, regenerate, delete, and a generation whose process
died.

The real FastAPI app over in-memory sources, a scripted model replying with
the fixture project, and a sandbox whose hidden tests follow the fixture's
rules (``tests/project_fakes.py``), signed in as the allowlisted account.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dayline.adapters.generated_source import InMemoryGeneratedProjectSource
from dayline.adapters.mock_source import InMemoryMockSource
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import SESSION_COOKIE, issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.api.services import mock_generate
from dayline.mock.project_gen import SUBMIT
from dayline.models import GeneratedProject, GenerationStatus
from tests.generated_projects import next_nest_tags
from tests.mock_fakes import FakeAnthropic, FakeMessages, small_rubric
from tests.project_fakes import SERVICE, RuleSandbox, tool_reply

ALLOWED = "owner@example.com"
BASE = "/api/mock/generated"
BODY: dict[str, Any] = {
    "prompt": "Next.js + Nest notes app where I add tagging; at 25 min they ask for filtering",
    "stack": "next-nest",
    "difficulty": "medium",
    "durationMin": 45,
    "changeRequestMin": 25,
    "contextFiles": [{"name": "past-round.md", "content": "# Past round\nThey asked for tags."}],
}


def _replies(count: int = 1) -> FakeMessages:
    return FakeMessages(
        [tool_reply(SUBMIT, next_nest_tags.submit_input(), f"tu_{i}") for i in range(count)]
    )


@pytest.fixture
def ctx() -> SimpleNamespace:
    return SimpleNamespace(
        task_source=InMemoryTaskSource(),
        mock_source=InMemoryMockSource(rubrics=[small_rubric()]),
        generated_source=InMemoryGeneratedProjectSource(),
        anthropic_client=FakeAnthropic(_replies(3)),
        sandbox=RuleSandbox(),
        client=None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, ctx: SimpleNamespace) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-not-for-production-use")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setattr("dayline.mock.project_check._POLL_S", 0.01)
    app = create_app()
    app.dependency_overrides[get_context] = lambda: ctx
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE, issue_session(ALLOWED, ALLOWED))
        yield c


def _create(client: TestClient, **changes: Any) -> dict[str, Any]:
    res = client.post(BASE, json=BODY | changes)
    assert res.status_code == 201, res.text
    return dict(res.json())


def _wait(client: TestClient, project_id: str, timeout: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    project = client.get(f"{BASE}/{project_id}").json()
    while project["status"] == "generating":
        assert time.monotonic() < deadline, project
        project = client.get(
            f"{BASE}/{project_id}", params={"version": project["version"] or 0, "wait": 1}
        ).json()
    return dict(project)


def test_a_project_generates_in_the_background_and_shows_only_what_the_candidate_may_see(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    created = _create(client)
    assert created["status"] == "generating" and created["progress"]["phase"] == "writing"
    project = _wait(client, created["id"])
    assert project["status"] == "ready", project["error"]
    assert project["title"] == "Tagged notes board"
    assert project["progress"]["phase"] == "ready"
    assert project["contextFiles"] == [{"name": "past-round.md", "bytes": 33}]
    assert project["usage"]["calls"] == 1 and project["usage"]["outputTokens"] == 500
    shown = project["project"]
    assert shown["files"]["README.md"] == next_nest_tags.README
    assert shown["task"]["title"] == "Tag notes"
    assert shown["changeRequest"] == {
        "title": "Filter by tag",
        "promptMd": next_nest_tags.submit_input()["change_request"]["prompt_md"],
        "targetMin": 20,
        "atMin": 25,
    }
    text = str(project)
    # Hidden tests, references, interviewer notes and grader hints stay on the server.
    assert "task: tags" not in text and "wanted" not in text
    assert "Watch whether" not in text and "analysis" not in text.lower()
    assert project["log"] == []
    # Imported context reached the model, marked as reference material.
    prompt = ctx.anthropic_client.messages.calls[0]["messages"][0]["content"]
    assert '<context name="past-round.md">' in prompt and "They asked for tags." in prompt
    # The validation sandbox is gone.
    assert ctx.sandbox.sandboxes == {}
    listed = client.get(BASE).json()
    assert [p["id"] for p in listed] == [created["id"]] and "project" not in listed[0]


def _blocking_model(ctx: SimpleNamespace) -> threading.Event:
    """Hold the model's stream until the returned event is set."""
    release = threading.Event()
    ctx.anthropic_client.messages.before_event = lambda _e: release.wait(5)
    return release


def test_one_generation_at_a_time_and_cancelling_stops_it(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    release = _blocking_model(ctx)
    created = _create(client)
    res = client.post(BASE, json=BODY)
    assert res.status_code == 409 and "already being generated" in res.json()["detail"]

    cancelled = client.post(f"{BASE}/{created['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    release.set()
    project = _wait(client, created["id"])
    assert project["status"] == "cancelled" and project["error"] == "Cancelled"
    deadline = time.monotonic() + 5
    while created["id"] in mock_generate._jobs:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert ctx.sandbox.sandboxes == {}
    # Free again.
    assert client.post(BASE, json=BODY).status_code == 201


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"contextFiles": [{"name": "diagram.png", "content": "x"}]}, "only text and code"),
        ({"stack": "django"}, "Pick a stack"),
        ({"changeRequestMin": 45}, "change request must come between"),
    ],
)
def test_bad_inputs_are_refused(client: TestClient, changes: dict[str, Any], message: str) -> None:
    res = client.post(BASE, json=BODY | changes)
    assert res.status_code == 400 and message in res.json()["detail"]


def test_a_failed_generation_keeps_its_attempt_log(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    broken = next_nest_tags.submit_input()
    broken["change_request"]["reference"] = [
        {"path": SERVICE, "content": next_nest_tags.SERVICE_TAGS + "// todo\n"}
    ]
    revise = {"change_request": broken["change_request"]}
    ctx.anthropic_client = FakeAnthropic(
        FakeMessages(
            [tool_reply(SUBMIT, broken, "tu_0")]
            + [tool_reply("revise_project", revise, f"tu_{i}") for i in range(1, 4)]
        )
    )
    project = _wait(client, _create(client)["id"])
    assert project["status"] == "failed"
    assert "after 3 repair attempts" in project["error"]
    assert [entry["attempt"] for entry in project["log"]] == [0, 1, 2, 3]
    assert project["usage"]["calls"] == 4 and project["project"] is None


def test_a_model_outage_fails_the_generation_clearly(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    ctx.anthropic_client = FakeAnthropic(FakeMessages([RuntimeError("boom")]))
    project = _wait(client, _create(client)["id"])
    assert project["status"] == "failed" and "boom" in project["error"]
    assert project["log"][-1]["kind"] == "crash"


def test_preview_then_start_a_round_in_the_project(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    project = _wait(client, _create(client)["id"])
    pid = project["id"]
    assert client.get(f"{BASE}/{pid}/preview").json() == {
        "state": "none",
        "base": None,
        "servers": [],
    }
    preview = client.post(f"{BASE}/{pid}/preview").json()
    assert preview["state"] == "running"
    assert preview["base"].startswith(f"/api/preview/gen-{pid}/")
    assert [s["name"] for s in preview["servers"]] == ["api", "web"]
    box = ctx.sandbox.sandboxes[f"gen-{pid}"]
    assert box["files"]["README.md"] == next_nest_tags.README
    # The app answers through the ordinary preview route.
    page = client.get(f"{preview['base']}/3000/")
    assert page.status_code == 200 and "Notes" in page.text
    logs = client.get(f"{BASE}/{pid}/servers/web/logs").json()
    assert logs["lines"] == ["web is ready"]
    assert client.post(f"{BASE}/{pid}/servers/web/explode").status_code == 400
    assert client.post(f"{BASE}/{pid}/servers/web/restart").json()["state"] == "running"
    # Starting again resumes the same sandbox.
    assert client.post(f"{BASE}/{pid}/preview").json()["base"] == preview["base"]

    res = client.post(f"{BASE}/{pid}/start", json={"rubricId": "rubric-1"})
    assert res.status_code == 201, res.text
    session = res.json()
    assert f"gen-{pid}" not in ctx.sandbox.sandboxes  # The preview made way.
    assert session["stagedProblemId"] == pid and session["assistant"] is True
    assert session["taskMd"] == next_nest_tags.README and session["durationMin"] == 45
    stages = session["staged"]["stages"]
    assert [s["status"] for s in stages] == ["active", "locked"]
    assert stages[0]["title"] == "Tag notes" and stages[1]["promptMd"] is None
    sid = session["id"]
    assert ctx.sandbox.sandboxes[sid]["files"]["README.md"] == next_nest_tags.README

    # The round runs on the stored problem: stage 1's hidden tests gate stage 1.
    run = client.post(f"{BASE.replace('generated', 'sessions')}/{sid}/stage/tests").json()
    assert run["passed"] is False
    ctx.sandbox.write_file(sid, SERVICE, next_nest_tags.SERVICE_TAGS, None)
    run = client.post(f"/api/mock/sessions/{sid}/stage/tests").json()
    assert run["passed"] is True
    assert [s["status"] for s in run["staged"]["stages"]] == ["passed", "active"]
    assert run["staged"]["stages"][1]["promptMd"].startswith("Product wants")

    # A session uses it now, so it cannot be deleted; ending and deleting
    # the session frees it.
    res = client.delete(f"{BASE}/{pid}")
    assert res.status_code == 409 and "Delete that session first" in res.json()["detail"]
    assert client.post(f"/api/mock/sessions/{sid}/end").status_code == 200
    ended = client.get(f"/api/mock/sessions/{sid}").json()
    assert ended["status"] == "ended" and "README.md" not in ended["finalDiff"]
    assert client.delete(f"/api/mock/sessions/{sid}").status_code == 204
    assert client.delete(f"{BASE}/{pid}").status_code == 204
    assert client.get(f"{BASE}/{pid}").status_code == 404


def test_regenerating_with_feedback_replaces_the_project(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    first = _wait(client, _create(client)["id"])
    client.post(f"{BASE}/{first['id']}/preview")
    res = client.post(f"{BASE}/{first['id']}/regenerate", json={"feedback": "Make it harder"})
    assert res.status_code == 201
    second = _wait(client, res.json()["id"])
    assert second["status"] == "ready" and second["feedback"] == "Make it harder"
    prompt = ctx.anthropic_client.messages.calls[1]["messages"][0]["content"]
    assert "<feedback>\nMake it harder\n</feedback>" in prompt
    assert 'The earlier one was "Tagged notes board"' in prompt
    assert "They asked for tags." in prompt  # The context files carried over.
    # The old project and its preview are gone.
    assert client.get(f"{BASE}/{first['id']}").status_code == 404
    assert f"gen-{first['id']}" not in ctx.sandbox.sandboxes
    assert [p["id"] for p in client.get(BASE).json()] == [second["id"]]


def test_a_generation_whose_process_died_reads_as_failed(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    project = ctx.generated_source.create(
        GeneratedProject(id="ghost", owner=ALLOWED, request={"stack": "next-nest"})
    )
    stored = ctx.generated_source._projects[project.id]
    stored.updated_at = datetime.now(UTC) - timedelta(minutes=11)
    shown = client.get(f"{BASE}/ghost").json()
    assert shown["status"] == "failed" and "server restarted" in shown["error"]
    # And it no longer blocks a new generation.
    assert client.post(BASE, json=BODY).status_code == 201


def test_projects_are_private_to_their_owner(client: TestClient, ctx: SimpleNamespace) -> None:
    ctx.generated_source.create(
        GeneratedProject(
            id="theirs",
            owner="someone@else.com",
            request={},
            status=GenerationStatus.READY,
        )
    )
    assert client.get(BASE).json() == []
    assert client.get(f"{BASE}/theirs").status_code == 404
    assert client.post(f"{BASE}/theirs/start", json={}).status_code == 404


def test_generating_needs_the_sandbox_runner(client: TestClient, ctx: SimpleNamespace) -> None:
    ctx.sandbox = None
    res = client.post(BASE, json=BODY)
    assert res.status_code == 503 and "SANDBOX_RUNNER_URL" in res.json()["detail"]
