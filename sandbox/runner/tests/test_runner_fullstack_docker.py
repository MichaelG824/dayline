"""The full-stack packs against a real Docker daemon: the built-in templates
boot their dev servers, pass their tests, run hidden tests, and serve the
app (HTTP and hot-reload WebSocket) through the preview proxy.

Opt in with ``RUN_DOCKER_TESTS=1``. The first run builds the pack images,
which takes a few minutes.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

docker = pytest.importorskip("docker")

from fastapi.testclient import TestClient  # noqa: E402

from dayline_runner.app import create_app  # noqa: E402
from dayline_runner.config import Settings  # noqa: E402
from dayline_runner.manager import SandboxError, SandboxManager  # noqa: E402
from dayline_runner.packs import load_packs  # noqa: E402

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1 to run"
    ),
]

ROOT = Path(__file__).resolve().parents[3]
PACKS_DIR = ROOT / "sandbox" / "packs"
TEMPLATES = ROOT / "src" / "dayline" / "mock" / "templates"
SECRET = "f" * 40


def _template(name: str) -> dict[str, str]:
    root = TEMPLATES / name / "files"
    return {p.relative_to(root).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def manager() -> Iterator[SandboxManager]:
    settings = Settings(
        secret=SECRET, idle_timeout_s=600, hard_cap_s=1800, retain_s=3600, max_running=4
    )
    m = SandboxManager(docker.from_env(), settings, load_packs(PACKS_DIR))
    m.build_packs()
    yield m
    for container in m._client.containers.list(all=True, filters={"label": "dayline.sandbox"}):
        if container.labels.get("dayline.sandbox.id", "").startswith("fs-test-"):
            m.destroy(container.labels["dayline.sandbox.id"])


@pytest.fixture(scope="module")
def client(manager: SandboxManager) -> Iterator[TestClient]:
    with TestClient(create_app(manager=manager, settings=Settings(secret=SECRET))) as c:
        yield c


def _start(manager: SandboxManager, pack: str, template: str) -> tuple[str, str]:
    sid = f"fs-test-{uuid.uuid4().hex[:8]}"
    base = f"/api/preview/{sid}/token{uuid.uuid4().hex}"
    manager.create(sid, pack, _template(template), base)
    deadline = time.time() + 240
    while time.time() < deadline:
        states = {s["name"]: s["state"] for s in manager.server_statuses(sid)}
        if all(state == "ready" for state in states.values()):
            return sid, base
        assert "exited" not in states.values(), manager.server_logs(sid, "web", 0)
        time.sleep(1)
    raise AssertionError(f"servers never became ready: {states}")


def _headers(base: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}", "X-Dayline-Preview-Base": base}


def test_next_nest_template_runs_tests_and_previews(
    manager: SandboxManager, client: TestClient
) -> None:
    sid, base = _start(manager, "next-nest", "notes-board-next-nest")
    report = manager.run_tests(sid)
    assert (report.status, report.passed) == ("passed", 3), report.output

    page = client.get(f"/sandboxes/{sid}/preview/3000", headers=_headers(base))
    assert page.status_code == 200 and "Notes board" in page.text
    assert f"{base}/3000/_next/static/" in page.text  # basePath reached the app.
    notes = client.post(
        f"/sandboxes/{sid}/preview/3000/api/notes",
        json={"text": "From the proxy"},
        headers=_headers(base),
    )
    assert notes.status_code == 201, notes.text
    assert (
        client.get(f"/sandboxes/{sid}/preview/4000/notes", headers=_headers(base)).json()[0]["text"]
        == "From the proxy"
    )

    # Turbopack's hot-reload socket, through the tunnel.
    with client.websocket_connect(
        f"/sandboxes/{sid}/preview/3000/_next/hmr?id=test", headers=_headers(base)
    ) as ws:
        assert ws.receive_text()

    hidden = {
        "api/service.test.ts": (
            "import 'reflect-metadata';\nimport { Test } from '@nestjs/testing';\n"
            "import { expect, it } from 'vitest';\n"
            "import { NotesController } from '../../../api/src/notes/notes.controller.js';\n"
            "import { NotesService } from '../../../api/src/notes/notes.service.js';\n"
            "it('injects', async () => {\n"
            "  const m = await Test.createTestingModule({ controllers: [NotesController],"
            " providers: [NotesService] }).compile();\n"
            "  expect(m.get(NotesController).list().length).toBe(1);\n});\n"
        ),
        "web/form.test.tsx": (
            "// @vitest-environment jsdom\n"
            "import { render, screen } from '@testing-library/react';\n"
            "import { expect, it, vi } from 'vitest';\n"
            "import { NoteForm } from '../../../web/app/NoteForm';\n"
            "vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));\n"
            "it('starts disabled', () => { render(<NoteForm />);"
            " expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled(); });\n"
        ),
    }
    hidden_report = manager.run_hidden_tests(sid, hidden)
    assert (hidden_report.status, hidden_report.passed) == ("passed", 2), hidden_report.output

    # Next's build output never shows in the file tree or the snapshot.
    assert not any(e.path.startswith("web/.next/") for e in manager.list_files(sid))
    snapshot = manager.snapshot(sid)["files"]
    assert "web/app/page.tsx" in snapshot and not any(".next/" in p for p in snapshot)


def test_rails_template_runs_tests_and_keeps_the_session_in_the_jar(
    manager: SandboxManager, client: TestClient
) -> None:
    sid, base = _start(manager, "rails", "notes-board-rails")
    report = manager.run_tests(sid)
    assert (report.status, report.passed) == ("passed", 4), report.output

    page = client.get(f"/sandboxes/{sid}/preview/3000", headers=_headers(base))
    assert page.status_code == 200 and f'action="{base}/3000/notes"' in page.text
    assert "set-cookie" not in page.headers  # The session cookie stays in the runner.
    token = re.search(r'name="authenticity_token" value="([^"]+)"', page.text)
    assert token
    created = client.post(
        f"/sandboxes/{sid}/preview/3000/notes",
        data={"authenticity_token": token.group(1), "note[text]": "From the jar"},
        headers={**_headers(base), "Origin": "http://localhost:3000"},
        follow_redirects=False,
    )
    assert created.status_code == 302, created.text
    after = client.get(f"/sandboxes/{sid}/preview/3000/notes", headers=_headers(base))
    assert (
        "Note added." in after.text and "From the jar" in after.text
    )  # The flash needs the session.

    hidden = {
        "note_search_test.rb": (
            'require "test_helper"\n\nclass NoteSearchTest < ActiveSupport::TestCase\n'
            '  test "passes" do\n    assert Note.new(text: "x").valid?\n  end\n\n'
            '  test "fails" do\n    assert_equal 2, 1 + 2\n  end\nend\n'
        )
    }
    outcomes = {c.name: c.outcome for c in manager.run_hidden_tests(sid, hidden).cases}
    assert outcomes == {"test_passes": "passed", "test_fails": "failed"}

    # Restart: the log says so, and the server comes back.
    manager.server_action(sid, "web", "restart")
    deadline = time.time() + 60
    while manager.server_statuses(sid)[0]["state"] != "ready" and time.time() < deadline:
        time.sleep(0.5)
    assert manager.server_statuses(sid)[0]["state"] == "ready"
    lines = manager.server_logs(sid, "web", 0)["lines"]
    assert sum("Starting web" in line for line in lines) == 2
    manager.server_action(sid, "web", "stop")
    assert manager.server_statuses(sid)[0]["state"] == "stopped"
    gone = client.get(f"/sandboxes/{sid}/preview/3000", headers=_headers(base))
    assert gone.status_code == 502 and gone.headers["x-dayline-preview-error"] == "1"

    # Binstubs stay executable; logs and databases stay out of the snapshot.
    code, _ = manager._exec(manager._running(sid), ["test", "-x", "bin/rails"])
    assert code == 0
    snapshot = manager.snapshot(sid)["files"]
    assert "app/models/note.rb" in snapshot
    assert not any(p.startswith(("log/", "tmp/", "storage/")) for p in snapshot)


def test_full_stack_sandboxes_stay_locked_down(manager: SandboxManager) -> None:
    sid, _ = _start(manager, "rails", "notes-board-rails")
    container = manager._running(sid)
    code, out = manager._exec(
        container, ["socat", "-u", "/dev/null", "TCP:1.1.1.1:80,connect-timeout=3"]
    )
    assert code != 0
    assert manager._exec(container, ["id", "-u"])[1].strip() == b"1000"
    assert manager._exec(container, ["touch", "/usr/local/bundle/owned"])[0] != 0


def test_projects_outside_the_pack_s_dependencies_are_refused(manager: SandboxManager) -> None:
    with pytest.raises(SandboxError, match="devise is not installed"):
        manager.create(f"fs-test-{uuid.uuid4().hex[:8]}", "rails", {"Gemfile": 'gem "devise"\n'})


def test_saves_are_written_from_inside_the_sandbox(manager: SandboxManager) -> None:
    sid, _ = _start(manager, "rails", "notes-board-rails")
    container = manager._running(sid)
    rails = manager.read_file(sid, "bin/rails")
    manager.write_file(sid, "bin/rails", rails["content"] + "# edited\n", rails["version"])
    saved = manager.write_file(sid, "lib/tasks/new/hello.rake", "task :hello\n", "")
    assert manager.read_file(sid, "lib/tasks/new/hello.rake")["version"] == saved["version"]
    modes = manager._exec(
        container, ["stat", "-c", "%a %U", "bin/rails", "lib/tasks/new/hello.rake"]
    )[1].split(b"\n")
    assert modes[:2] == [b"755 candidate", b"644 candidate"]
    # The staging copies are gone.
    assert (
        manager._exec(container, ["sh", "-c", "ls -A .dayline/incoming | wc -l"])[1].strip() == b"0"
    )
    with pytest.raises(SandboxError, match="Could not write"):
        manager.write_file(sid, "app", "not a folder", None)
