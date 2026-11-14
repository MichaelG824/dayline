"""Mock tab API: question bank + ingest, rubrics, guidelines, sessions, grading,
and weak areas -> prep tasks through the existing chat confirm path.

Runs the real FastAPI app over in-memory sources (no Supabase) with a scripted
Anthropic client, signed in as the allowlisted account.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dayline.adapters.mock_source import InMemoryMockSource
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import issue_session
from dayline.api.chat import ChatDeps
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.api.services import chat as chat_service
from dayline.mock.grader import MAX_ATTEMPTS
from dayline.models import MockGuideline
from tests.mock_fakes import (
    TRANSCRIPT,
    FakeAnthropic,
    FakeMessages,
    scorecard_payload,
    small_rubric,
)

ALLOWED = "owner@example.com"


@pytest.fixture
def ctx() -> SimpleNamespace:
    return SimpleNamespace(
        task_source=InMemoryTaskSource(),
        mock_source=InMemoryMockSource(
            rubrics=[small_rubric()],
            guidelines=[MockGuideline(id="g1", name="Strict", body_md="Be strict.")],
        ),
        anthropic_client=FakeAnthropic(FakeMessages([])),
        sandbox=None,
        client=None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, ctx: SimpleNamespace) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-not-for-production-use")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("MOCK_GRADER_MODEL", "grader-under-test")
    app = create_app()
    app.dependency_overrides[get_context] = lambda: ctx
    with TestClient(
        app, headers={"Authorization": f"Bearer {issue_session(ALLOWED, ALLOWED)}"}
    ) as c:
        yield c


def _script(ctx: SimpleNamespace, *tool_calls: tuple[str, dict[str, Any]]) -> FakeAnthropic:
    fake = FakeAnthropic.replying(*tool_calls)
    ctx.anthropic_client = fake
    return fake


def _create_question(client: TestClient, **fields: Any) -> dict[str, Any]:
    body = {
        "title": "LRU cache",
        "roundType": "Algorithm",
        "promptMd": "Build an LRU cache.",
        **fields,
    }
    res = client.post("/api/mock/questions", json=body)
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_mock_routes_require_sign_in(client: TestClient) -> None:
    for path in ("/api/mock/questions", "/api/mock/sessions", "/api/mock/rubrics"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401


def test_question_crud_and_validation(client: TestClient) -> None:
    created = _create_question(client, company=" Acme ", followUps=["Add TTL", " "])
    assert created["company"] == "Acme"
    assert created["followUps"] == ["Add TTL"]
    assert created["source"] == "own"
    assert created["timesSeen"] == 1

    patched = client.patch(
        f"/api/mock/questions/{created['id']}", json={"reportedOn": "2026-10-03", "role": ""}
    ).json()
    assert patched["reportedOn"] == "2026-10-03"
    assert patched["role"] is None

    assert client.post("/api/mock/questions", json={"title": "x"}).status_code == 400
    bad_round = client.patch(f"/api/mock/questions/{created['id']}", json={"roundType": "Quiz"})
    assert bad_round.status_code == 400
    bad_date = client.patch(f"/api/mock/questions/{created['id']}", json={"reportedOn": "Oct"})
    assert bad_date.status_code == 400

    assert client.delete(f"/api/mock/questions/{created['id']}").status_code == 204
    assert client.get(f"/api/mock/questions/{created['id']}").status_code == 404


def test_copies_point_at_the_root_and_are_counted(client: TestClient) -> None:
    root = _create_question(client)
    copy1 = _create_question(client, title="LRU again", canonicalId=root["id"])
    # "Same as copy1" resolves to copy1's root, so links stay one level deep.
    copy2 = _create_question(client, title="LRU third time", canonicalId=copy1["id"])
    assert copy2["canonicalId"] == root["id"]

    listed = client.get("/api/mock/questions").json()
    assert [(q["id"], q["timesSeen"]) for q in listed] == [(root["id"], 3)]
    detail = client.get(f"/api/mock/questions/{root['id']}").json()
    assert {c["id"] for c in detail["copies"]} == {copy1["id"], copy2["id"]}

    self_link = client.patch(f"/api/mock/questions/{root['id']}", json={"canonicalId": copy1["id"]})
    assert self_link.status_code == 400


def test_extract_suggests_existing_duplicates_and_saves_nothing(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    existing = _create_question(
        client, promptMd="Design a least recently used cache with get and put in O(1)."
    )
    _script(
        ctx,
        (
            "record_questions",
            {
                "original_language": "zh",
                "questions": [
                    {
                        "title": "Implement LRU cache",
                        "round_type": "Algorithm",
                        "prompt_md": "Implement a least recently used cache: get and put in O(1).",
                        "follow_ups": ["Make it thread-safe"],
                    }
                ],
            },
        ),
    )
    res = client.post("/api/mock/extract", json={"text": "电面: LRU cache, 追问 thread-safe"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["originalLanguage"] == "zh"
    [q] = body["questions"]
    assert q["followUps"] == ["Make it thread-safe"]
    assert [s["id"] for s in q["similar"]] == [existing["id"]]
    assert len(client.get("/api/mock/questions").json()) == 1


def test_extract_errors_are_400(client: TestClient) -> None:
    assert client.post("/api/mock/extract", json={"text": "  "}).status_code == 400


def test_rubric_validation_and_key_derivation(client: TestClient) -> None:
    res = client.post(
        "/api/mock/rubrics",
        json={
            "name": "System design",
            "roundType": "System design",
            "criteria": [
                {"title": "Clarifies requirements!", "weight": 2},
                {"key": "tradeoffs", "title": "Tradeoffs"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    assert [c["key"] for c in res.json()["criteria"]] == ["clarifies_requirements", "tradeoffs"]

    def post(criteria: list[dict[str, Any]]) -> int:
        return client.post(
            "/api/mock/rubrics", json={"name": "R", "criteria": criteria}
        ).status_code

    assert post([]) == 400
    assert post([{"title": ""}]) == 400
    assert post([{"title": "A", "weight": 0}]) == 400
    assert post([{"title": "A", "weight": "heavy"}]) == 400
    assert post([{"title": "Same"}, {"title": "same"}]) == 400


def test_guideline_crud(client: TestClient) -> None:
    created = client.post("/api/mock/guidelines", json={"name": "Kind", "bodyMd": "Be kind."})
    assert created.status_code == 201
    gid = created.json()["id"]
    updated = client.put(f"/api/mock/guidelines/{gid}", json={"name": "Kinder", "bodyMd": "x"})
    assert updated.json()["name"] == "Kinder"
    assert client.put(f"/api/mock/guidelines/{gid}", json={"name": " "}).status_code == 400
    names = [g["name"] for g in client.get("/api/mock/guidelines").json()]
    assert names == ["Kinder", "Strict"]


def _create_session(client: TestClient, **fields: Any) -> dict[str, Any]:
    body = {"title": "Library mock", "transcript": TRANSCRIPT, "rubricId": "rubric-1", **fields}
    res = client.post("/api/mock/sessions", json=body)
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_session_validation(client: TestClient) -> None:
    assert client.post("/api/mock/sessions", json={"transcript": " "}).status_code == 400
    missing = client.post("/api/mock/sessions", json={"transcript": "hi", "rubricId": "nope"})
    assert missing.status_code == 404
    ungraded = _create_session(client, rubricId=None)
    assert ungraded["scorecard"] is None
    assert client.post(f"/api/mock/sessions/{ungraded['id']}/grade").status_code == 400


def test_grade_then_turn_weak_areas_into_linked_tasks(
    client: TestClient, ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The confirm path's Supabase-bound pieces (preference/outcome tables,
    # re-planning) are out of scope here; apply_proposal itself runs for real.
    empty: list[dict[str, Any]] = []
    deps = ChatDeps(
        task_source=ctx.task_source,
        get_plan=lambda _day: {},
        list_interviews=lambda: empty,
        get_category_ranks=lambda: empty,
        get_preferences=lambda: {},
        get_recent_outcomes=lambda _n: empty,
    )
    monkeypatch.setattr(chat_service, "build_chat_deps", lambda _ctx: deps)
    monkeypatch.setattr(chat_service, "plan_day", lambda _ctx, _day: {"blocks": []})
    question = _create_question(client, followUps=["What about concurrency?"])
    session = _create_session(client, questionId=question["id"], guidelineId="g1")
    fake = _script(ctx, ("submit_scorecard", scorecard_payload()))

    graded = client.post(f"/api/mock/sessions/{session['id']}/grade")
    assert graded.status_code == 200, graded.text
    body = graded.json()
    card = body["scorecard"]
    assert card["overallScore"] == 2.5
    assert card["graderModel"] == "grader-under-test"
    assert card["criteria"][1]["evidence"][1] == {
        "quote": "I always verify AI output",
        "verified": False,
    }
    prompt = fake.messages.calls[0]["messages"][0]["content"]
    assert "Be strict." in prompt and "What about concurrency?" in prompt

    listed = client.get("/api/mock/sessions").json()
    assert [(s["id"], s["overallScore"]) for s in listed] == [(session["id"], 2.5)]

    # Weak areas go through the existing confirm endpoint, never a new path.
    [proposal] = body["proposals"]
    confirmed = client.post(
        "/api/chat/confirm",
        json={"day": "2026-11-13", "proposals": [proposal], "offered": body["proposals"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    tasks = [t for t in ctx.task_source.list_tasks() if t.mock_session_id == session["id"]]
    assert [t.name for t in tasks] == ["Practise explaining race conditions and row locks"]

    detail = client.get(f"/api/mock/sessions/{session['id']}").json()
    assert [t["name"] for t in detail["tasks"]] == [tasks[0].name]
    assert detail["transcript"] == TRANSCRIPT


def test_regrading_keeps_the_newest_card(client: TestClient, ctx: SimpleNamespace) -> None:
    session = _create_session(client)
    lower = scorecard_payload()
    lower["criteria"][0]["score"] = 1
    _script(ctx, ("submit_scorecard", scorecard_payload()), ("submit_scorecard", lower))
    client.post(f"/api/mock/sessions/{session['id']}/grade")
    regraded = client.post(f"/api/mock/sessions/{session['id']}/grade").json()
    # (1*1 + 2*3) / 4 = 1.75
    assert regraded["scorecard"]["overallScore"] == 1.75


def test_grader_failure_is_422(client: TestClient, ctx: SimpleNamespace) -> None:
    session = _create_session(client)
    bad = scorecard_payload(criteria=[])
    _script(ctx, *[("submit_scorecard", bad)] * MAX_ATTEMPTS)
    res = client.post(f"/api/mock/sessions/{session['id']}/grade")
    assert res.status_code == 422
    assert "Missing criteria" in res.json()["detail"]


def test_deleting_a_session_removes_its_scorecard(client: TestClient, ctx: SimpleNamespace) -> None:
    session = _create_session(client)
    _script(ctx, ("submit_scorecard", scorecard_payload()))
    client.post(f"/api/mock/sessions/{session['id']}/grade")
    assert client.delete(f"/api/mock/sessions/{session['id']}").status_code == 204
    assert client.get("/api/mock/sessions").json() == []
    assert ctx.mock_source.latest_scorecards() == {}
