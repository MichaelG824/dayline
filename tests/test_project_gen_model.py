"""The project generator against the real model and real sandboxes: one
small project per stack is written by the model (the default, Claude Sonnet
5.5, or ``MOCK_GENERATOR_MODEL``), checked, repaired if needed, and
validated end to end.

Opt in with ``RUN_MODEL_TESTS=1 RUN_DOCKER_TESTS=1`` (needs Anthropic
credentials and Docker; a few minutes and well under a dollar per stack).
Run with ``-s`` to watch the phases.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("RUN_MODEL_TESTS") != "1" or os.environ.get("RUN_DOCKER_TESTS") != "1",
        reason="set RUN_MODEL_TESTS=1 and RUN_DOCKER_TESTS=1 to run",
    ),
]

docker = pytest.importorskip("docker")

import anthropic  # noqa: E402

from dayline.adapters.sandbox import RunnerSandboxClient  # noqa: E402
from dayline.mock import generator_model  # noqa: E402
from dayline.mock.project_gen import Hooks, Usage, generate  # noqa: E402
from dayline.mock.project_spec import STACKS, parse_request, staged_problem  # noqa: E402
from dayline.mock.templates import builtin_templates  # noqa: E402
from tests.runner_harness import running_runner  # noqa: E402

PROMPTS = {
    "next-nest": (
        "A Next.js + Nest bookmarks app. I add starring a bookmark; at 20 minutes they ask "
        "me to sort starred bookmarks first."
    ),
    "rails": (
        "A Rails reading-list app. I add marking a book as read; at 20 minutes they ask me to "
        "show a count of unread books."
    ),
}


@pytest.fixture(scope="module")
def runner() -> Iterator[RunnerSandboxClient]:
    with running_runner(("genchk-",)) as client:
        yield client


@pytest.mark.parametrize("stack", ["next-nest", "rails"])
def test_the_model_writes_a_project_that_validates(
    runner: RunnerSandboxClient, stack: str
) -> None:
    request = parse_request(
        prompt=PROMPTS[stack],
        stack=stack,
        difficulty="easy",
        duration_min=40,
        change_request_min=20,
        context_files=[("past-round.md", "# Past round\nSmall CRUD app, one feature, one tweak.")],
    )
    pack = next(p for p in runner.packs() if p["name"] == STACKS[stack].pack)
    log: list[str] = []
    usage = Usage()
    result = generate(
        anthropic.Anthropic(),
        generator_model(),
        runner,
        request,
        builtin_templates()[STACKS[stack].template].files,
        dict(pack["dependencies"]["allowed"]),
        Hooks(
            progress=lambda phase, attempt, detail: print(f"[{attempt}] {phase}: {detail}"),
            log=lambda attempt, kind, message: log.append(f"[{attempt}] {kind}: {message}"),
            new_sandbox_id=lambda: f"genchk-{uuid.uuid4().hex[:12]}",
        ),
        usage,
    )
    print("\n".join(log))
    print(f"{stack}: {result.attempts} attempt(s), usage {usage.to_json()}")
    problem = staged_problem("model-test", result.artifact)
    assert len(problem.stages) == 2
    assert all(stage.cases for stage in problem.stages)
    assert usage.calls >= result.attempts and usage.output_tokens > 0
