"""Allowlist gate: unauthenticated 401, other accounts 403, allowed email through.

Hits one read route (``GET /api/tasks``) and one write route (``POST /api/tasks``)
so a missing gate on either side cannot hide. The task source is an in-memory
fake; these tests never talk to Google or Supabase.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.auth import issue_session
from dayline.api.context import get_context
from dayline.api.main import create_app

ALLOWED = "owner@example.com"
OTHER = "someone.else@gmail.com"
DAY = "2026-09-10"


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-not-for-production-use")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")


@pytest.fixture
def client(auth_env: None) -> Iterator[TestClient]:
    app = create_app()
    source = InMemoryTaskSource()
    ctx = SimpleNamespace(task_source=source, client=None)
    app.dependency_overrides[get_context] = lambda: ctx
    with TestClient(app) as test_client:
        yield test_client


def _auth_header(email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_session(email, email)}"}


def test_health_is_public(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_unauthenticated_read_is_401(client: TestClient) -> None:
    res = client.get(f"/api/tasks?day={DAY}")
    assert res.status_code == 401
    assert res.json()["detail"] == "Sign in required"


def test_unauthenticated_write_is_401(client: TestClient) -> None:
    res = client.post(
        "/api/tasks",
        json={"name": "Drill", "category": "Other", "estDurationMin": 30, "priority": "P2"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Sign in required"


def test_other_account_read_is_403(client: TestClient) -> None:
    res = client.get(f"/api/tasks?day={DAY}", headers=_auth_header(OTHER))
    assert res.status_code == 403
    assert "not allowed" in res.json()["detail"].lower()


def test_other_account_write_is_403(client: TestClient) -> None:
    res = client.post(
        "/api/tasks",
        json={"name": "Drill", "category": "Other", "estDurationMin": 30, "priority": "P2"},
        headers=_auth_header(OTHER),
    )
    assert res.status_code == 403
    assert "not allowed" in res.json()["detail"].lower()


def test_allowed_email_read_is_200(client: TestClient) -> None:
    res = client.get(f"/api/tasks?day={DAY}", headers=_auth_header(ALLOWED))
    assert res.status_code == 200
    assert res.json() == []


def test_allowed_email_write_is_201(client: TestClient) -> None:
    res = client.post(
        "/api/tasks",
        json={"name": "Drill", "category": "Other", "estDurationMin": 30, "priority": "P2"},
        headers=_auth_header(ALLOWED),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Drill"
    assert body["priority"] == "P2"


def test_allowed_email_is_case_insensitive(client: TestClient) -> None:
    res = client.get(
        f"/api/tasks?day={DAY}",
        headers=_auth_header("Owner@example.com"),
    )
    assert res.status_code == 200


def test_me_unauthenticated_is_401(client: TestClient) -> None:
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_reports_denied_account(client: TestClient) -> None:
    res = client.get("/api/auth/me", headers=_auth_header(OTHER))
    assert res.status_code == 200
    assert res.json() == {"email": OTHER, "allowed": False}


def test_session_cookie_also_authenticates(client: TestClient) -> None:
    client.cookies.set("dayline_session", issue_session(ALLOWED, ALLOWED))
    res = client.get(f"/api/tasks?day={DAY}")
    assert res.status_code == 200


def test_blank_allowlist_denies_every_account(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOWED_EMAIL", raising=False)
    res = client.get(f"/api/tasks?day={DAY}", headers=_auth_header(ALLOWED))
    assert res.status_code == 403


def test_google_login_redirects_to_google(client: TestClient) -> None:
    res = client.get("/api/auth/google", follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-google-client-id" in location
    assert "hd=" not in location
