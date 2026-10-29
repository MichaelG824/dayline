"""Problems tab API: problems, solutions, tags, and task links.

Runs the real FastAPI app over in-memory sources (no Supabase), signed in as
the allowlisted account, so each test exercises controller -> service ->
adapter end to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dayline.adapters.problem_source import InMemoryProblemSource
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app
from dayline.models import ProblemTag

ALLOWED = "owner@example.com"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-not-for-production-use")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    app = create_app()
    ctx = SimpleNamespace(
        task_source=InMemoryTaskSource(),
        problem_source=InMemoryProblemSource(
            tags=[
                ProblemTag(id="tag-arrays", name="Arrays", color="#2563eb"),
                ProblemTag(id="tag-dp", name="Dynamic Programming", color="#4f46e5"),
            ]
        ),
        client=None,
    )
    app.dependency_overrides[get_context] = lambda: ctx
    with TestClient(
        app, headers={"Authorization": f"Bearer {issue_session(ALLOWED, ALLOWED)}"}
    ) as c:
        yield c


def _create(client: TestClient, **fields: Any) -> dict[str, Any]:
    body = {"title": "Two Sum", "difficulty": "Easy", **fields}
    res = client.post("/api/problems", json=body)
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_problems_require_sign_in(client: TestClient) -> None:
    res = client.get("/api/problems", headers={"Authorization": ""})
    assert res.status_code == 401


def test_create_list_and_get_problem(client: TestClient) -> None:
    created = _create(
        client,
        number=1,
        url="https://leetcode.com/problems/two-sum/",
        notes="Use a hash map.",
        tagIds=["tag-arrays"],
    )
    assert created["status"] == "To do"
    assert created["tagIds"] == ["tag-arrays"]
    assert created["createdAt"] is not None

    listed = client.get("/api/problems").json()
    assert [p["id"] for p in listed] == [created["id"]]

    detail = client.get(f"/api/problems/{created['id']}").json()
    assert detail["title"] == "Two Sum"
    assert detail["notes"] == "Use a hash map."
    assert detail["solutions"] == []
    assert detail["tasks"] == []


def test_starred_problems_list_first(client: TestClient) -> None:
    plain = _create(client, title="Plain")
    starred = _create(client, title="Starred", starred=True)
    newest = _create(client, title="Newest")
    ids = [p["id"] for p in client.get("/api/problems").json()]
    assert ids == [starred["id"], newest["id"], plain["id"]]


def test_unknown_problem_is_404(client: TestClient) -> None:
    assert client.get("/api/problems/nope").status_code == 404
    assert client.patch("/api/problems/nope", json={"starred": True}).status_code == 404


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"title": "   "}, "Title is required"),
        ({"difficulty": "Impossible"}, "Unknown difficulty"),
        ({"status": "Done"}, "Unknown problem status"),
        ({"confidence": 6}, "Confidence must be 1-5"),
        ({"number": 0}, "Number must be positive"),
        ({"tagIds": ["tag-missing"]}, "Unknown tags"),
    ],
)
def test_create_rejects_invalid_fields(
    client: TestClient, fields: dict[str, Any], detail: str
) -> None:
    body = {"title": "Two Sum", "difficulty": "Easy", **fields}
    res = client.post("/api/problems", json=body)
    assert res.status_code == 400
    assert detail in res.json()["detail"]


def test_create_requires_title_and_difficulty(client: TestClient) -> None:
    res = client.post("/api/problems", json={"title": "Two Sum"})
    assert res.status_code == 400


def test_patch_changes_only_sent_fields(client: TestClient) -> None:
    created = _create(client, number=1, notes="keep me", tagIds=["tag-arrays"])
    res = client.patch(f"/api/problems/{created['id']}", json={"starred": True})
    updated = res.json()
    assert updated["starred"] is True
    assert updated["notes"] == "keep me"
    assert updated["number"] == 1
    assert updated["tagIds"] == ["tag-arrays"]


def test_patch_null_clears_a_nullable_field(client: TestClient) -> None:
    created = _create(client, number=1, url="https://leetcode.com/problems/two-sum/")
    updated = client.patch(
        f"/api/problems/{created['id']}", json={"number": None, "url": ""}
    ).json()
    assert updated["number"] is None
    assert updated["url"] is None


def test_status_transitions_stamp_timestamps(client: TestClient) -> None:
    created = _create(client)
    assert created["lastAttemptedAt"] is None
    assert created["solvedAt"] is None
    pid = created["id"]

    attempted = client.patch(f"/api/problems/{pid}", json={"status": "Attempted"}).json()
    assert attempted["lastAttemptedAt"] is not None

    solved = client.patch(f"/api/problems/{pid}", json={"status": "Solved"}).json()
    assert solved["solvedAt"] is not None
    assert solved["lastAttemptedAt"] == attempted["lastAttemptedAt"]

    # Re-solving after a review keeps the first solve date.
    client.patch(f"/api/problems/{pid}", json={"status": "Review"})
    resolved = client.patch(f"/api/problems/{pid}", json={"status": "Solved"}).json()
    assert resolved["solvedAt"] == solved["solvedAt"]


def test_problem_created_as_attempted_is_stamped(client: TestClient) -> None:
    created = _create(client, status="Attempted")
    assert created["lastAttemptedAt"] is not None


def test_solutions_crud_and_ordering(client: TestClient) -> None:
    pid = _create(client)["id"]
    brute = client.post(
        f"/api/problems/{pid}/solutions",
        json={
            "title": "Brute force",
            "language": "python",
            "code": "pass",
            "timeComplexity": "O(n^2)",
        },
    ).json()
    optimal = client.post(
        f"/api/problems/{pid}/solutions",
        json={
            "title": "Hash map",
            "language": "python",
            "code": "seen = {}",
            "timeComplexity": "O(n)",
            "spaceComplexity": " ",
            "isOptimal": True,
        },
    ).json()
    assert optimal["spaceComplexity"] is None

    solutions = client.get(f"/api/problems/{pid}").json()["solutions"]
    assert [s["id"] for s in solutions] == [optimal["id"], brute["id"]]

    res = client.put(
        f"/api/solutions/{brute['id']}",
        json={"title": "Brute force (nested loops)", "language": "go", "code": "x"},
    )
    assert res.json()["title"] == "Brute force (nested loops)"
    assert res.json()["language"] == "go"
    assert res.json()["createdAt"] == brute["createdAt"]

    assert client.delete(f"/api/solutions/{brute['id']}").status_code == 204
    solutions = client.get(f"/api/problems/{pid}").json()["solutions"]
    assert [s["id"] for s in solutions] == [optimal["id"]]


def test_solution_validation(client: TestClient) -> None:
    pid = _create(client)["id"]
    missing = client.post("/api/problems/nope/solutions", json={"title": "x", "language": "python"})
    assert missing.status_code == 404
    blank = client.post(f"/api/problems/{pid}/solutions", json={"title": " ", "language": "python"})
    assert blank.status_code == 400
    assert (
        client.put("/api/solutions/nope", json={"title": "x", "language": "go"}).status_code == 404
    )


def test_deleting_problem_removes_its_solutions(client: TestClient) -> None:
    pid = _create(client)["id"]
    sid = client.post(
        f"/api/problems/{pid}/solutions", json={"title": "Hash map", "language": "python"}
    ).json()["id"]
    assert client.delete(f"/api/problems/{pid}").status_code == 204
    assert client.get(f"/api/problems/{pid}").status_code == 404
    assert (
        client.put(f"/api/solutions/{sid}", json={"title": "x", "language": "go"}).status_code
        == 404
    )


def test_tags_crud_counts_and_uniqueness(client: TestClient) -> None:
    _create(client, tagIds=["tag-arrays"])
    _create(client, title="Climbing Stairs", tagIds=["tag-arrays", "tag-dp"])

    tags = {t["name"]: t for t in client.get("/api/problem-tags").json()}
    assert tags["Arrays"]["problemCount"] == 2
    assert tags["Dynamic Programming"]["problemCount"] == 1

    created = client.post("/api/problem-tags", json={"name": "Heap", "color": "#f59e0b"})
    assert created.status_code == 201
    assert created.json()["problemCount"] == 0

    dup = client.post("/api/problem-tags", json={"name": "arrays"})
    assert dup.status_code == 409

    renamed = client.put("/api/problem-tags/tag-dp", json={"name": "DP", "color": None})
    assert renamed.json() == {"id": "tag-dp", "name": "DP", "color": None, "problemCount": 1}
    rename_clash = client.put("/api/problem-tags/tag-dp", json={"name": "Heap"})
    assert rename_clash.status_code == 409
    assert client.put("/api/problem-tags/nope", json={"name": "Zzz"}).status_code == 404


def test_deleting_tag_detaches_it_from_problems(client: TestClient) -> None:
    pid = _create(client, tagIds=["tag-arrays", "tag-dp"])["id"]
    assert client.delete("/api/problem-tags/tag-dp").status_code == 204
    assert client.get(f"/api/problems/{pid}").json()["tagIds"] == ["tag-arrays"]


def test_task_links_to_problem(client: TestClient) -> None:
    pid = _create(client)["id"]
    res = client.post(
        "/api/tasks",
        json={
            "name": "Solve: Two Sum",
            "category": "Leetcode",
            "priority": "P1",
            "estDurationMin": 45,
            "problemId": pid,
        },
    )
    assert res.status_code == 201
    task = res.json()
    assert task["problemId"] == pid

    linked = client.get(f"/api/problems/{pid}").json()["tasks"]
    assert [t["id"] for t in linked] == [task["id"]]


def test_task_with_unknown_problem_is_404(client: TestClient) -> None:
    res = client.post(
        "/api/tasks",
        json={
            "name": "Solve: ghost",
            "category": "Leetcode",
            "priority": "P1",
            "estDurationMin": 45,
            "problemId": "nope",
        },
    )
    assert res.status_code == 404


def test_export_includes_solutions_and_tags(client: TestClient) -> None:
    pid = _create(client, tagIds=["tag-arrays"])["id"]
    client.post(f"/api/problems/{pid}/solutions", json={"title": "Hash map", "language": "python"})
    export = client.get("/api/problems/export").json()
    assert export["version"] == 1
    assert export["problems"][0]["solutions"][0]["title"] == "Hash map"
    assert {t["name"] for t in export["tags"]} == {"Arrays", "Dynamic Programming"}
