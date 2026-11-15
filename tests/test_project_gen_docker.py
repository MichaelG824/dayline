"""Generated projects validated in real sandboxes: each stack's fixture
project passes every check through a real runner over HTTP (dev servers
boot, the preview answers, visible tests pass, hidden tests fail before and
pass after each reference), a deliberately broken reference fails
validation, and the cases validation records let a staged round tell the
stages apart in the stack's own test runner.

Opt in with ``RUN_DOCKER_TESTS=1``. The first run builds the pack images.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

docker = pytest.importorskip("docker")

from dayline.adapters.sandbox import RunnerSandboxClient  # noqa: E402
from dayline.mock import staged  # noqa: E402
from dayline.mock.project_check import check_project  # noqa: E402
from dayline.mock.project_gen import artifact_from_submit  # noqa: E402
from dayline.mock.project_spec import (  # noqa: E402
    STACKS,
    Artifact,
    parse_request,
    staged_problem,
    static_problems,
)
from dayline.mock.templates import builtin_templates  # noqa: E402
from dayline.models import StageStatus  # noqa: E402
from tests.generated_projects import next_nest_tags, rails_tags  # noqa: E402
from tests.runner_harness import running_runner  # noqa: E402

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1 to run"
    ),
]

FIXTURES = {"next-nest": next_nest_tags, "rails": rails_tags}


@pytest.fixture(scope="module")
def runner() -> Iterator[RunnerSandboxClient]:
    with running_runner(("gentest-", "genround-")) as client:
        yield client


def _artifact(stack: str, change: dict[str, Any] | None = None) -> Artifact:
    request = parse_request(
        prompt="A notes app where I add tagging; later they ask for filtering",
        stack=stack,
        difficulty="medium",
        duration_min=45,
        change_request_min=25,
        context_files=[],
    )
    data = FIXTURES[stack].submit_input()
    if change:
        data["change_request"] |= change
    scaffold = builtin_templates()[STACKS[stack].template].files
    artifact = artifact_from_submit(data, request, scaffold)
    assert static_problems(artifact) == []
    return artifact


def _check(runner: RunnerSandboxClient, artifact: Artifact) -> tuple[Any, list[tuple[str, str]]]:
    steps: list[tuple[str, str]] = []
    sid = f"gentest-{uuid.uuid4().hex[:10]}"
    result = check_project(
        runner,
        artifact,
        sandbox_id=sid,
        preview_base=f"/api/preview/{sid}/{uuid.uuid4().hex}",
        step=lambda phase, detail: steps.append((phase, detail)),
    )
    return result, steps


@pytest.mark.parametrize("stack", ["next-nest", "rails"])
def test_the_fixture_project_validates_and_its_cases_drive_a_round(
    runner: RunnerSandboxClient, stack: str
) -> None:
    artifact = _artifact(stack)
    result, steps = _check(runner, artifact)
    assert result.ok, "\n\n".join(result.problems)
    phases = [phase for phase, _ in steps]
    assert phases[0] == "checking_dependencies" and "booting" in phases
    assert phases[-1] == "running_tests"
    task_cases, change_cases = result.cases
    assert task_cases and change_cases and not set(task_cases) & set(change_cases)
    # Edge cases now name the recorded tests; a title that matched no test is gone.
    edges = {e.id: e.tests for e in artifact.task.edge_cases}
    assert all(t in {n for _, n in task_cases} for tests in edges.values() for t in tests)
    if stack == "next-nest":
        assert len(edges["limit"]) == 1
        assert any("does not exist" in note for note in result.notes)

    # The stored problem, run as a round: the stage-1 tests gate stage 1 on
    # real JUnit output (classnames are paths for Vitest, classes for Minitest).
    problem = staged_problem("p-1", Artifact.from_json(artifact.to_json()))
    sid = f"genround-{uuid.uuid4().hex[:10]}"
    runner.create(sid, problem.pack, artifact.files)
    try:
        attempts = staged.new_round(problem, datetime.now(UTC))
        report = runner.run_hidden_tests(sid, staged.hidden_files(problem, attempts))
        assert staged.record_run(problem, attempts, report) is False
        for path, content in artifact.task.reference.items():
            runner.write_file(sid, path, content, None)
        report = runner.run_hidden_tests(sid, staged.hidden_files(problem, attempts))
        assert staged.record_run(problem, attempts, report) is True, report["output"]
        staged.finish_stage(attempts, StageStatus.PASSED, {}, datetime.now(UTC))
        # Stage 2 runs both stages' tests; only stage 2's are failing.
        report = runner.run_hidden_tests(sid, staged.hidden_files(problem, attempts))
        assert staged.record_run(problem, attempts, report) is False
        failing = {c["name"] for c in report["cases"] if c["outcome"] != "passed"}
        assert failing and failing <= problem.stages[1].test_names
    finally:
        runner.destroy(sid)


def test_a_broken_reference_fails_validation(runner: RunnerSandboxClient) -> None:
    # A change-request "solution" that never filters: its tests cannot pass.
    broken = next_nest_tags.submit_input()["change_request"]
    broken["reference"] = [
        {"path": "api/src/notes/notes.service.ts", "content": next_nest_tags.SERVICE_TAGS + "\n"}
    ]
    result, _ = _check(runner, _artifact("next-nest", broken))
    assert not result.ok
    assert any("must pass once both reference solutions" in p for p in result.problems)
    assert result.cases == ([], [])
