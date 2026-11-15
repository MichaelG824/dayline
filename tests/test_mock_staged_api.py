"""Staged rounds through the API: start, gate each stage on its hidden tests,
skip, talk to the interviewer, end, and grade.

The real FastAPI app over in-memory sources and the in-memory sandbox fake,
signed in as the allowlisted account. Hidden test runs are real: the fake
sandbox hands them to ``tests/staged_harness.py``, which runs them against the
sandbox's files in a subprocess the way the runner would.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dayline.adapters.mock_source import InMemoryMockSource
from dayline.adapters.sandbox import InMemorySandboxClient
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import SESSION_COOKIE, issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.mock.staged import builtin_staged_problems
from tests.mock_fakes import (
    FakeAnthropic,
    FakeMessages,
    FakeResponse,
    FakeText,
    scorecard_payload,
    small_rubric,
)
from tests.staged_harness import run_hidden

ALLOWED = "owner@example.com"
PROBLEM = "lru-cache"
SOLUTION = "lru_cache.py"
LRU = builtin_staged_problems()[PROBLEM]


def _replies(*texts: str) -> FakeMessages:
    return FakeMessages([FakeResponse([FakeText(t)]) for t in texts])


@pytest.fixture
def ctx() -> SimpleNamespace:
    sandbox = InMemorySandboxClient()
    context = SimpleNamespace(
        task_source=InMemoryTaskSource(),
        mock_source=InMemoryMockSource(rubrics=[small_rubric()]),
        anthropic_client=FakeAnthropic(_replies()),
        sandbox=sandbox,
        client=None,
    )

    def run_against_the_workspace(hidden: dict[str, str]) -> dict[str, Any]:
        (box,) = sandbox.sandboxes.values()
        return run_hidden(box["files"], hidden)

    sandbox.hidden_report = run_against_the_workspace
    return context


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
    res = client.post("/api/mock/staged/sessions", json={"problemId": PROBLEM, **fields})
    assert res.status_code == 201, res.text
    return dict(res.json())


def _write(client: TestClient, sid: str, code: str) -> None:
    res = client.put(f"/api/mock/sessions/{sid}/files/{SOLUTION}", json={"content": code})
    assert res.status_code == 200, res.text


def _run(client: TestClient, sid: str) -> dict[str, Any]:
    res = client.post(f"/api/mock/sessions/{sid}/stage/tests")
    assert res.status_code == 200, res.text
    return dict(res.json())


def _statuses(staged: dict[str, Any]) -> list[str]:
    return [s["status"] for s in staged["stages"]]


def test_availability_lists_staged_problems_without_giving_the_stages_away(
    client: TestClient,
) -> None:
    live = client.get("/api/mock/live").json()
    (problem,) = live["stagedProblems"]
    assert (problem["id"], problem["stageCount"], problem["pack"]) == (PROBLEM, 4, "python")
    assert not any(stage.title in str(problem) for stage in LRU.stages)


def test_a_round_starts_on_stage_1_with_the_rest_locked(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    session = _start(client, rubricId="rubric-1")
    assert (session["kind"], session["status"], session["stagedProblemId"]) == (
        "live",
        "live",
        PROBLEM,
    )
    assert ctx.sandbox.sandboxes[session["id"]]["files"] == LRU.starter
    assert session["openPath"] == SOLUTION and session["taskMd"].startswith("# Staged round")
    staged = session["staged"]
    assert staged["activeStage"] == 1
    assert _statuses(staged) == ["active", "locked", "locked", "locked"]
    first, locked = staged["stages"][0], staged["stages"][1]
    assert first["title"] == "Base LRU cache" and "## Stage 1" in first["promptMd"]
    # Nothing about a locked stage, and no edge cases while a stage is live.
    assert (locked["title"], locked["promptMd"]) == (None, None)
    assert first["edgeCases"] == []
    # Interviewer notes and hidden tests never reach the client.
    body = str(session)
    assert LRU.stages[0].notes_md[:40] not in body
    assert "def test_" not in body


def test_bad_starts_leave_nothing_behind(client: TestClient, ctx: SimpleNamespace) -> None:
    res = client.post("/api/mock/staged/sessions", json={"problemId": "nope"})
    assert res.status_code == 404
    ctx.sandbox.unavailable = True
    res = client.post("/api/mock/staged/sessions", json={"problemId": PROBLEM})
    assert res.status_code == 503
    assert client.get("/api/mock/sessions").json() == []


def test_a_stage_unlocks_only_when_its_hidden_tests_pass(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]

    failing = _run(client, sid)  # The starter raises NotImplementedError.
    assert failing["passed"] is False and failing["report"]["status"] == "failed"
    assert _statuses(failing["staged"]) == ["active", "locked", "locked", "locked"]
    # The hidden files went to the runner, and only stage 1's.
    assert list(ctx.sandbox.hidden_runs[-1]) == ["test_stage_1_base.py"]

    _write(client, sid, LRU.references[1])
    passing = _run(client, sid)
    assert passing["passed"] is True
    staged = passing["staged"]
    assert _statuses(staged) == ["passed", "active", "locked", "locked"]
    assert staged["activeStage"] == 2
    assert staged["stages"][1]["title"] == "Per-entry TTL"
    done = staged["stages"][0]
    assert done["runs"] == 2 and done["finishedAt"]
    # A finished stage's edge cases show: failed on the first run, fixed later.
    assert {e["id"]: e["outcome"] for e in done["edgeCases"]} == {
        "update_existing_key": "caught",
        "falsy_values": "caught",
    }

    # Stage 2's run includes stage 1's tests, so a regression blocks it.
    broken = LRU.references[2].replace("self._unlink(node)\n        self._push", "self._push")
    _write(client, sid, broken)
    regressed = _run(client, sid)
    assert regressed["passed"] is False
    assert set(ctx.sandbox.hidden_runs[-1]) == {"test_stage_1_base.py", "test_stage_2_ttl.py"}
    stage_1_failures = [
        c for c in regressed["report"]["cases"]
        if c["classname"] == "test_stage_1_base" and c["outcome"] != "passed"
    ]  # fmt: skip
    assert stage_1_failures

    events = client.get(f"/api/mock/sessions/{sid}").json()["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.count("stage_tests_run") == 3 and kinds.count("stage_passed") == 1
    assert events[kinds.index("stage_passed")]["data"] == {"stage": 1}


def test_a_full_round_passes_every_stage(client: TestClient) -> None:
    sid = _start(client)["id"]
    for stage in (1, 2, 3, 4):
        _write(client, sid, LRU.references[stage])
        assert _run(client, sid)["passed"] is True
    session = client.get(f"/api/mock/sessions/{sid}").json()
    assert session["staged"]["activeStage"] is None
    assert _statuses(session["staged"]) == ["passed"] * 4
    assert (session["stageCount"], session["stagesPassed"]) == (4, 4)
    designs = [s["design"] for s in session["staged"]["stages"]]
    assert designs[0] is None and all(d["verdict"] == "extended" for d in designs[1:])
    # Nothing left to run or skip.
    assert client.post(f"/api/mock/sessions/{sid}/stage/tests").status_code == 409
    assert client.post(f"/api/mock/sessions/{sid}/stage/skip").status_code == 409


def test_skipping_is_recorded_and_drops_that_stages_tests(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    _write(client, sid, LRU.references[1])
    assert _run(client, sid)["passed"] is True

    skipped = client.post(f"/api/mock/sessions/{sid}/stage/skip").json()
    assert _statuses(skipped) == ["passed", "skipped", "active", "locked"]
    edges = {e["id"]: e["outcome"] for e in skipped["stages"][1]["edgeCases"]}
    assert edges == {"expired_but_present": "missed", "put_resets_ttl": "missed"}

    # Stage 2's TTL tests are left out of later runs.
    _write(client, sid, LRU.references[3])
    assert _run(client, sid)["passed"] is True
    assert set(ctx.sandbox.hidden_runs[-1]) == {"test_stage_1_base.py", "test_stage_3_weighted.py"}
    kinds = [e["kind"] for e in client.get(f"/api/mock/sessions/{sid}").json()["events"]]
    assert "stage_skipped" in kinds


def test_staged_routes_refuse_plain_live_sessions(client: TestClient) -> None:
    res = client.post("/api/mock/live/sessions", json={"templateId": "library-late-fees"})
    sid = res.json()["id"]
    assert client.post(f"/api/mock/sessions/{sid}/stage/tests").status_code == 404
    assert client.get(f"/api/mock/sessions/{sid}").json()["staged"] is None


def test_the_interviewer_opens_each_stage_once_from_the_candidates_code(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    ctx.anthropic_client = FakeAnthropic(_replies("Hi! Let's start.", "Nice. Now entries expire."))
    sid = _start(client)["id"]
    url = f"/api/mock/sessions/{sid}/interviewer"

    opened = client.post(url, json={"trigger": "stage_start"}).json()
    (opener,) = opened["chat"]
    assert (opener["role"], opener["text"]) == ("interviewer", "Hi! Let's start.")
    assert opener["stage"] == 1
    # A reload asks again: no second opener, no model call.
    again = client.post(url, json={"trigger": "stage_start"}).json()
    assert len(again["chat"]) == 1 and len(ctx.anthropic_client.messages.calls) == 1

    _write(client, sid, LRU.references[1])
    _run(client, sid)
    client.post(url, json={"trigger": "stage_start"})
    call = ctx.anthropic_client.messages.calls[1]
    prompt = call["messages"][0]["content"]
    # Grounded in the candidate's code and the new stage, with the private notes.
    assert "def _push_front(self, node):" in prompt
    assert "## Stage 2: entries expire" in prompt
    assert LRU.stages[1].notes_md.strip()[:60] in prompt
    assert "its hidden tests passed" in prompt
    assert call["model"] and "Never write the solution" in call["system"]


def test_candidate_messages_get_replies_and_survive_a_failed_reply(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    sid = _start(client)["id"]
    url = f"/api/mock/sessions/{sid}/interviewer"
    ctx.anthropic_client = FakeAnthropic(_replies("Why a doubly linked list?"))
    said = "I'll use a dict plus a doubly linked list."
    chat = client.post(url, json={"trigger": "message", "message": said}).json()["chat"]
    assert [(m["role"], m["text"]) for m in chat] == [
        ("candidate", said),
        ("interviewer", "Why a doubly linked list?"),
    ]
    assert said in ctx.anthropic_client.messages.calls[0]["messages"][0]["content"]

    assert client.post(url, json={"trigger": "message", "message": "  "}).status_code == 400
    ctx.anthropic_client = FakeAnthropic(_replies(""))  # The model says nothing.
    res = client.post(url, json={"trigger": "message", "message": "Unlinking needs prev."})
    assert res.status_code == 502
    chat = client.get(f"/api/mock/sessions/{sid}").json()["staged"]["chat"]
    assert chat[-1] == {**chat[-1], "role": "candidate", "text": "Unlinking needs prev."}


def test_ending_closes_the_active_stage_and_grading_sees_the_round(
    client: TestClient, ctx: SimpleNamespace
) -> None:
    ctx.anthropic_client = FakeAnthropic(_replies("Walk me through your get."))
    sid = _start(client, rubricId="rubric-1")["id"]
    client.post(
        f"/api/mock/sessions/{sid}/interviewer",
        json={"trigger": "message", "message": "Starting with a hash map."},
    )
    _write(client, sid, LRU.references[1])
    _run(client, sid)
    # Stage 2 attempted with the expiry check missing, then the round ends.
    _write(client, sid, LRU.references[2].replace("self._clock() >= node.expires_at", "False"))
    _run(client, sid)

    ended = client.post(f"/api/mock/sessions/{sid}/end").json()
    staged = ended["staged"]
    assert _statuses(staged) == ["passed", "failed", "locked", "locked"]
    stage_2 = staged["stages"][1]
    assert stage_2["timeSpentS"] is not None and stage_2["design"]["verdict"] == "extended"
    assert {e["id"]: e["outcome"] for e in stage_2["edgeCases"]}["expired_but_present"] == "missed"
    # Ended: every reached stage's edge cases show; locked ones stay hidden.
    assert staged["stages"][2]["title"] is None
    assert "Candidate: Starting with a hash map." in ended["transcript"]
    assert "Interviewer: Walk me through your get." in ended["transcript"]
    timeline_kinds = {e["kind"] for e in ended["events"]}
    assert {"stage_passed", "stage_tests_run", "session_ended"} <= timeline_kinds

    ctx.anthropic_client = FakeAnthropic.replying(("submit_scorecard", scorecard_payload()))
    graded = client.post(f"/api/mock/sessions/{sid}/grade")
    assert graded.status_code == 200, graded.text
    prompt = ctx.anthropic_client.messages.calls[0]["messages"][0]["content"]
    assert "## Staged round: Production LRU cache" in prompt
    assert "Stage 2 (Per-entry TTL): failed" in prompt
    assert "An expired key still in the map is never returned: missed" in prompt
    assert "ran stage 1's hidden tests: passed" in prompt
    # The chat is the transcript the grader verifies quotes against.
    assert "Starting with a hash map." in prompt
