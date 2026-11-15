"""The runner's HTTP surface: every route needs the shared secret."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from dayline_runner.app import create_app
from dayline_runner.config import Settings
from dayline_runner.manager import SandboxConflict, SandboxNotFound

SECRET = "s" * 40


class StubManager:
    def pack_statuses(self) -> list[dict[str, Any]]:
        return [{"name": "python", "state": "ready"}]

    def write_file(self, *_: Any) -> dict[str, Any]:
        raise SandboxConflict("app.py changed since it was opened")

    def stop_background(self) -> None:
        pass

    def preview_path(self, sandbox_id: str, port: int, base: str, suffix: str) -> str:
        raise SandboxNotFound("No such preview")

    def dependency_problems(self, pack: str, files: dict[str, str]) -> list[str]:
        return [f"{path}: nope" for path in files]


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


def test_preview_needs_the_secret_and_marks_the_runners_own_refusals() -> None:
    with _client() as client:
        assert client.get("/sandboxes/s1/preview/3000/").status_code == 401
        response = client.get(
            "/sandboxes/s1/preview/3000/notes",
            headers={"Authorization": f"Bearer {SECRET}", "X-Dayline-Preview-Base": "/x"},
        )
        assert response.status_code == 404
        assert response.headers["x-dayline-preview-error"] == "1"
        assert response.json()["detail"] == "No such preview"


def test_dependency_check_route() -> None:
    with _client() as client:
        response = client.post(
            "/packs/rails/check",
            json={"files": {"Gemfile": "gem 'x'"}},
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        assert response.json() == {"problems": ["Gemfile: nope"]}
