"""The runner's HTTP surface: every route needs the shared secret."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from dayline_runner.app import create_app
from dayline_runner.config import Settings
from dayline_runner.manager import SandboxConflict

SECRET = "s" * 40


class StubManager:
    def pack_statuses(self) -> list[dict[str, Any]]:
        return [{"name": "python", "state": "ready"}]

    def write_file(self, *_: Any) -> dict[str, Any]:
        raise SandboxConflict("app.py changed since it was opened")

    def stop_background(self) -> None:
        pass


def _client() -> TestClient:
    app = create_app(manager=StubManager(), settings=Settings(secret=SECRET))  # type: ignore[arg-type]
    return TestClient(app)


def test_requests_without_the_secret_are_rejected() -> None:
    with _client() as client:
        assert client.get("/health").status_code == 200
        assert client.get("/packs").status_code == 401
        assert client.get("/packs", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = client.get("/packs", headers={"Authorization": f"Bearer {SECRET}"})
        assert ok.status_code == 200 and ok.json()[0]["name"] == "python"


def test_sandbox_errors_map_to_their_status() -> None:
    with _client() as client:
        response = client.put(
            "/sandboxes/s1/files/app.py",
            json={"content": "x", "baseVersion": "abc"},
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "app.py changed since it was opened"


def test_short_secrets_are_refused(monkeypatch: Any) -> None:
    monkeypatch.setenv("SANDBOX_RUNNER_SECRET", "short")
    try:
        Settings.from_env()
    except RuntimeError as exc:
        assert "at least 32" in str(exc)
    else:
        raise AssertionError("expected a RuntimeError")
