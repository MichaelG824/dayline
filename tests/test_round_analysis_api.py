"""A generated AI-assisted round end to end through the API: the change
request arrives by the server's clock (and survives a reload), the realistic
interviewer delivers it and stays quiet otherwise, the session replays
moment by moment, and the analysis gets metrics, hints, and key points that
cite real moments, which become "Practise next" proposals.

The real FastAPI app over in-memory sources, a scripted model, and a sandbox
whose hidden tests follow the fixture project's rules
(``tests/project_fakes.py``), signed in as the allowlisted account. Time
passes by moving everything stored about the round back (:func:`_travel`).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
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
from dayline.mock.project_gen import SUBMIT
from dayline.models import MockRoundType, MockRubric
from tests.generated_projects import next_nest_tags
from tests.mock_fakes import FakeAnthropic, FakeMessages, FakeResponse, FakeText, FakeToolUse
from tests.project_fakes import SERVICE, RuleSandbox, tool_reply
from tests.round_fixture import seeded_rubric

ALLOWED = "owner@example.com"
BASE = "/api/mock/generated"
BODY: dict[str, Any] = {
    "prompt": "Next.js + Nest notes app where I add tagging; at 25 min they ask for filtering",
    "stack": "next-nest",
    "difficulty": "medium",
    "durationMin": 45,
    "changeRequestMin": 25,
    "contextFiles": [],
}


@pytest.fixture
def messages() -> FakeMessages:
    return FakeMessages([tool_reply(SUBMIT, next_nest_tags.submit_input())])


@pytest.fixture
def ctx(messages: FakeMessages) -> SimpleNamespace:
    return SimpleNamespace(
        task_source=InMemoryTaskSource(),
        mock_source=InMemoryMockSource(rubrics=[seeded_rubric()]),
        generated_source=InMemoryGeneratedProjectSource(),
        anthropic_client=FakeAnthropic(messages),
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


def _ready_project(client: TestClient) -> str:
    project = client.post(BASE, json=BODY).json()
    deadline = time.monotonic() + 10
    while project["status"] == "generating":
        assert time.monotonic() < deadline, project
        project = client.get(
            f"{BASE}/{project['id']}", params={"version": project["version"] or 0, "wait": 1}
        ).json()
    assert project["status"] == "ready", project
    return str(project["id"])


def _start(client: TestClient, **body: Any) -> dict[str, Any]:
    res = client.post(f"{BASE}/{_ready_project(client)}/start", json=body)
    assert res.status_code == 201, res.text
    return dict(res.json())


def _travel(ctx: SimpleNamespace, sid: str, minutes: float) -> None:
    """Pretend ``minutes`` passed: move everything stored about the round
    back by that much (the in-memory source's own records)."""
    delta = timedelta(minutes=minutes)
    session = ctx.mock_source._sessions[sid]
    session.started_at -= delta
    for attempt in session.stages:
        attempt.started_at = attempt.started_at and attempt.started_at - delta
        attempt.finished_at = attempt.finished_at and attempt.finished_at - delta
    for event in ctx.mock_source._events:
        if event.session_id == sid:
            event.at -= delta


def _say(messages: FakeMessages, *texts: str) -> None:
    messages.responses += [FakeResponse([FakeText(t)]) for t in texts]


def _interviewer(client: TestClient, sid: str, trigger: str, text: str | None = None) -> Any:
    res = client.post(
        f"/api/mock/sessions/{sid}/interviewer", json={"trigger": trigger, "message": text}
    )
    assert res.status_code == 200, res.text
    return res.json()


def _assistant(client: TestClient, sid: str, mode: str, prompt: str) -> list[dict[str, Any]]:
    res = client.post(
        f"/api/mock/sessions/{sid}/assistant/turns", json={"mode": mode, "prompt": prompt}
    )
    assert res.status_code == 200, res.text
    return [json.loads(f.removeprefix("data: ")) for f in res.text.split("\n\n") if f.strip()]


def _kinds(ctx: SimpleNamespace, sid: str, kind: str) -> list[dict[str, Any]]:
    return [dict(e.data) for e in ctx.mock_source.list_events(sid) if e.kind == kind]


def _scorecard(rubric: MockRubric, whys: list[str]) -> dict[str, Any]:
    return {
        "summary": "Explored first and planned, then rushed the change request.",
        "strengths": ["Planned before the first edit"],
        "criteria": [
            {
                "key": c.key,
                "score": 2 if c.key == "diff_review" else 3,
                "evidence": (
                    ["25:00 the change request (stage 2) arrived on schedule"]
                    if c.key == "change_request"
                    else []
                ),
                "improvement": "Keep it up.",
            }
            for c in rubric.criteria
        ],
        "weak_areas": [
            {
                "title": f"Point {i}",
                "why": why,
                "task_name": f"Practise point {i}",
                "category": "AI Coding (React/Python)",
                "est_duration_min": 30,
            }
            for i, why in enumerate(whys, start=1)
        ],
    }


def test_a_generated_round_runs_on_the_clock_replays_and_is_analysed(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    session = _start(client, rubricId="ai-fullstack")
    sid = session["id"]
    staged = session["staged"]
    assert staged["interviewerStyle"] == "realistic" and staged["activeStage"] == 1
    due = datetime.fromisoformat(staged["changeRequest"]["dueAt"])
    assert due - datetime.fromisoformat(session["startedAt"]) == timedelta(minutes=25)
    assert staged["changeRequest"]["arrivedAt"] is None and staged["serverNow"]

    # The interviewer opens briefly; a check-in while all is well says nothing
    # and costs no model call.
    _say(messages, "Hi. The task is in front of you; ask me about requirements any time.")
    _interviewer(client, sid, "stage_start")
    calls = len(messages.calls)
    quiet = _interviewer(client, sid, "check_in")
    assert len(messages.calls) == calls and len(quiet["chat"]) == 1

    # Plan, then an edit, accepted after 3 seconds.
    _travel(ctx, sid, 2)
    _say(messages, "1. Normalise tags in `NotesService.create`. 2. Return them.")
    _assistant(client, sid, "plan", "Plan adding tags in `NotesService.create`")
    _travel(ctx, sid, 2)
    messages.responses += [
        FakeResponse(
            [
                FakeToolUse(
                    "propose_edit",
                    {
                        "path": SERVICE,
                        "summary": "Tags.",
                        "new_content": next_nest_tags.SERVICE_TAGS,
                    },
                )
            ]
        ),
        FakeResponse([FakeText("Added tags.")]),
    ]
    frames = _assistant(client, sid, "edit", "Add tags to notes in `NotesService.create`")
    (proposal,) = frames[-1]["turn"]["proposals"]
    _travel(ctx, sid, 0.05)
    res = client.post(
        f"/api/mock/sessions/{sid}/assistant/edits/{proposal['id']}", json={"decision": "accept"}
    )
    assert res.json()["status"] == "accepted"

    # Stage 1 passes early: the candidate stays on it until the minute.
    run = client.post(f"/api/mock/sessions/{sid}/stage/tests").json()
    assert run["passed"] is True
    assert [s["status"] for s in run["staged"]["stages"]] == ["passed", "locked"]
    assert run["staged"]["activeStage"] == 1 and run["staged"]["canBringEarly"] is True

    # 26 minutes in, a plain read brings the change request, stamped 25:00;
    # reading again (a reload) brings nothing new.
    _travel(ctx, sid, 22)
    for _ in range(2):
        detail = client.get(f"/api/mock/sessions/{sid}").json()
    stages = detail["staged"]["stages"]
    assert [s["status"] for s in stages] == ["passed", "active"]
    started = datetime.fromisoformat(detail["startedAt"])
    change = detail["staged"]["changeRequest"]
    assert datetime.fromisoformat(change["arrivedAt"]) - started == timedelta(minutes=25)
    assert change["early"] is False and change["dueAt"] is None
    assert detail["staged"]["canBringEarly"] is False
    assert _kinds(ctx, sid, "stage_unlocked") == [{"stage": 2, "early": False}]

    # The interviewer delivers it in its own words.
    _say(messages, "OK, the PM just came back - people want to see only the notes with one tag.")
    delivered = _interviewer(client, sid, "stage_start")
    assert delivered["chat"][-1]["text"].startswith("OK, the PM just came back")
    prompt = messages.calls[-1]["messages"][0]["content"]
    assert "Interrupt the candidate with it in your own words" in prompt
    assert "Product wants" in prompt  # The change request's own prompt.
    # A repeat (another tab, a reload) never says it twice.
    calls = len(messages.calls)
    _interviewer(client, sid, "stage_start")
    assert len(messages.calls) == calls

    _travel(ctx, sid, 1)
    _say(messages, "An empty list. Unknown tags are not an error.")
    _interviewer(client, sid, "message", "Should an unknown tag return an empty list or a 404?")
    assert "give no hint" in messages.calls[-1]["messages"][0]["content"]

    _travel(ctx, sid, 3)
    res = client.put(
        f"/api/mock/sessions/{sid}/files/{SERVICE}", json={"content": next_nest_tags.SERVICE_FILTER}
    )
    assert res.status_code == 200
    run = client.post(f"/api/mock/sessions/{sid}/stage/tests").json()
    assert run["passed"] is True and run["staged"]["activeStage"] is None
    _travel(ctx, sid, 5)
    assert client.post(f"/api/mock/sessions/{sid}/end").status_code == 200

    # The replay: every moment, the change request at 25:00, saves with diffs.
    replay = client.get(f"/api/mock/sessions/{sid}/replay").json()
    entries = replay["entries"]
    assert replay["changeRequestS"] == 25 * 60 and replay["durationS"] >= 35 * 60
    assert [e["t"] for e in entries] == sorted(e["t"] for e in entries)
    kinds = [e["kind"] for e in entries]
    for kind in (
        "session_started",
        "interviewer_message",
        "assistant_prompt",
        "assistant_response",
        "assistant_edit_proposed",
        "assistant_edit_decided",
        "file_saved",
        "stage_tests_run",
        "stage_passed",
        "stage_unlocked",
        "candidate_message",
        "session_ended",
    ):
        assert kind in kinds, kind
    proposed = next(e for e in entries if e["kind"] == "assistant_edit_proposed")
    assert proposed["meta"]["outcome"] == "accepted" and "+" in proposed["diff"]
    decided = next(e for e in entries if e["kind"] == "assistant_edit_decided")
    assert re.fullmatch(rf"Accepted the AI's edit to {SERVICE} after \d\.\ds", decided["title"])
    saves = [e for e in entries if e["kind"] == "file_saved"]
    assert len(saves) == 2 and all(e["diff"].startswith("--- a/") for e in saves)
    prompts = [e["meta"]["mode"] for e in entries if e["kind"] == "assistant_prompt"]
    assert prompts == ["plan", "edit"]
    assert any(
        m.startswith("Change request: arrived at 25:00 (on schedule)") for m in replay["metrics"]
    )

    # The analysis: the first card's key points cite nothing and go back;
    # the second cites the change request's moment.
    rubric = seeded_rubric()
    vague = ["Rushed the change request.", "Accepted edits quickly.", "Test more."]
    cited = [
        "At 25:00 the change request arrived and the first edit came minutes later with no plan.",
        "The 25:00 change request got no clarifying plan in the assistant.",
        "Verify after each accepted edit; after 25:00 only one hidden run happened.",
    ]
    messages.responses += [
        FakeResponse([FakeToolUse("submit_scorecard", _scorecard(rubric, vague), "tu_g1")]),
        FakeResponse([FakeToolUse("submit_scorecard", _scorecard(rubric, cited), "tu_g2")]),
    ]
    graded = client.post(f"/api/mock/sessions/{sid}/grade").json()
    first, retry = messages.calls[-2:]
    record = first["messages"][0]["content"]
    assert "## Round metrics (computed in code" in record
    assert "Change request: arrived at 25:00 (on schedule)" in record
    assert "Accepted edits reviewed under 10s: 1/1 (100%)" in record
    assert "## What to look for in this round (interviewer hints)" in record
    assert "25:00 the change request (stage 2) arrived on schedule" in record
    assert "key points to improve" in first["system"]
    feedback = retry["messages"][-1]["content"][0]["content"]
    assert "Key point 1 ('Point 1'): its why must cite a moment" in feedback

    card = graded["scorecard"]
    change = next(c for c in card["criteria"] if c["key"] == "change_request")
    assert change["evidence"] == [
        {"quote": "25:00 the change request (stage 2) arrived on schedule", "verified": True}
    ]
    assert [w["why"] for w in card["weakAreas"]] == cited
    # Key points flow into "Practise next" as prep-task proposals.
    assert [p["name"] for p in graded["proposals"]] == [
        "Practise point 1",
        "Practise point 2",
        "Practise point 3",
    ]
    assert all(p["mock_session_id"] == sid for p in graded["proposals"])


def test_done_early_brings_the_change_request_and_the_coach_style_is_kept(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    sid = _start(client, interviewerStyle="coach")["id"]
    refused = client.post(f"/api/mock/sessions/{sid}/stage/bring-early")
    assert refused.status_code == 409  # Stage 1 is still in progress.
    ctx.sandbox.write_file(sid, SERVICE, next_nest_tags.SERVICE_TAGS, None)
    client.post(f"/api/mock/sessions/{sid}/stage/tests")
    _travel(ctx, sid, 12)
    brought = client.post(f"/api/mock/sessions/{sid}/stage/bring-early").json()
    assert [s["status"] for s in brought["stages"]] == ["passed", "active"]
    assert brought["interviewerStyle"] == "coach"
    change = brought["changeRequest"]
    assert change["early"] is True
    arrived = datetime.fromisoformat(change["arrivedAt"])
    started = datetime.fromisoformat(client.get(f"/api/mock/sessions/{sid}").json()["startedAt"])
    assert timedelta(minutes=11) < arrived - started < timedelta(minutes=13)
    # Its minute passing later changes nothing.
    _travel(ctx, sid, 20)
    client.get(f"/api/mock/sessions/{sid}")
    assert _kinds(ctx, sid, "stage_unlocked") == [{"stage": 2, "early": True}]
    # The coach delivers the change request and asks where it lands.
    _say(messages, "Filtering by tag just came in. Which part of your service changes first?")
    _interviewer(client, sid, "stage_start")
    assert (
        "which part of their current code it touches first"
        in (messages.calls[-1]["messages"][0]["content"])
    )
    assert messages.calls[-1]["system"].startswith("You are the interviewer in a staged")


def test_a_check_in_speaks_when_the_candidate_is_clearly_stuck(
    client: TestClient, ctx: SimpleNamespace, messages: FakeMessages
) -> None:
    sid = _start(client)["id"]
    for _ in range(3):
        client.post(f"/api/mock/sessions/{sid}/stage/tests")  # Fails: nothing written yet.
    _say(messages, "Where are you at with it?")
    said = _interviewer(client, sid, "check_in")
    assert said["chat"][-1]["text"] == "Where are you at with it?"
    assert "3 test runs in a row have not passed" in messages.calls[-1]["messages"][0]["content"]
    # Right after it spoke, another check-in stays quiet.
    calls = len(messages.calls)
    _interviewer(client, sid, "check_in")
    assert len(messages.calls) == calls


def test_the_end_brings_a_change_request_that_came_due_unseen(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    _travel(ctx, sid, 30)
    client.post(f"/api/mock/sessions/{sid}/end")
    stages = client.get(f"/api/mock/sessions/{sid}").json()["staged"]["stages"]
    assert [s["status"] for s in stages] == ["failed", "failed"]
    assert _kinds(ctx, sid, "stage_unlocked") == [{"stage": 2, "early": False}]


def test_the_seeded_rubric_names_every_analysis_criterion() -> None:
    rubric = seeded_rubric()
    assert rubric.name == "AI-assisted full-stack round"
    assert rubric.round_type is MockRoundType.AI_ASSISTED_PROJECT
    assert [c.key for c in rubric.criteria] == [
        "understanding",
        "prompting",
        "plan_first",
        "diff_review",
        "verification",
        "change_request",
        "time_management",
        "correctness",
    ]


def test_replays_are_for_live_sessions_only(client: TestClient) -> None:
    res = client.post("/api/mock/sessions", json={"title": "Pasted", "transcript": "Hi"})
    assert client.get(f"/api/mock/sessions/{res.json()['id']}/replay").status_code == 404
