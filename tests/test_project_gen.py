"""The project generator with a fake model and a fake sandbox: reading the
model's output, the rules code enforces, the sandbox verdicts (including a
deliberately broken reference), the bounded repair loop, and the staged
problem a validated project becomes."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from dayline.mock import project_gen, staged
from dayline.mock.project_check import Cancelled, check_project, map_edge_cases
from dayline.mock.project_gen import (
    REVISE,
    SUBMIT,
    GenerationFailed,
    Hooks,
    InvalidOutput,
    Usage,
    artifact_from_revise,
    artifact_from_submit,
    generate,
)
from dayline.mock.project_spec import (
    MAX_CONTEXT_FILE_BYTES,
    STACKS,
    Artifact,
    RequestError,
    parse_request,
    staged_problem,
    static_problems,
)
from dayline.mock.templates import builtin_templates
from dayline.models import MockRoundType, StageAttempt, StageStatus
from tests.generated_projects import next_nest_tags, rails_tags
from tests.mock_fakes import FakeAnthropic, FakeMessages
from tests.project_fakes import SERVICE, RuleSandbox, text_reply, tool_reply

SCAFFOLD = builtin_templates()[STACKS["next-nest"].template].files
RAILS_SCAFFOLD = builtin_templates()[STACKS["rails"].template].files


def _request(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "prompt": "Next.js + Nest notes app where I add tagging; at 25 min they ask for filtering",
        "stack": "next-nest",
        "difficulty": "medium",
        "duration_min": 45,
        "change_request_min": 25,
        "context_files": [],
    }
    return parse_request(**(fields | overrides))


def _submit() -> dict[str, Any]:
    return next_nest_tags.submit_input()


def _artifact(data: dict[str, Any] | None = None) -> Artifact:
    return artifact_from_submit(data or _submit(), _request(), SCAFFOLD)


# -- inputs --------------------------------------------------------------------------


def test_a_good_request_keeps_text_context_files() -> None:
    request = _request(context_files=[("notes/past-round.md", "# Past round\nTagging...")])
    assert request.context_files[0].name == "past-round.md"
    assert request.to_json()["changeRequestMin"] == 25


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"prompt": "  "}, "Describe the round"),
        ({"stack": "django"}, "Pick a stack"),
        ({"difficulty": "brutal"}, "Pick a difficulty"),
        ({"duration_min": 10}, "must last"),
        ({"change_request_min": 44}, "between minute 5 and minute 40"),
        ({"change_request_min": 2}, "between minute"),
        ({"context_files": [("diagram.png", "x")]}, "only text and code files"),
        ({"context_files": [("notes.md", "a\x00b")]}, "binary"),
        ({"context_files": [("big.md", "x" * (MAX_CONTEXT_FILE_BYTES + 1))]}, "under 64 KB"),
        ({"context_files": [(f"f{i}.md", "x") for i in range(11)]}, "at most 10"),
        ({"context_files": [(f"f{i}.md", "x" * 60_000) for i in range(5)]}, "total under"),
    ],
)
def test_requests_outside_the_limits_are_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(RequestError, match=message):
        _request(**overrides)


# -- reading the model's output ----------------------------------------------------


def test_a_submission_is_written_on_top_of_the_scaffold() -> None:
    data = _submit() | {"delete": ["web/app/NoteForm.test.tsx", "no/such/file.ts"]}
    artifact = artifact_from_submit(data, _request(), SCAFFOLD)
    assert artifact.files["README.md"] == next_nest_tags.README
    assert artifact.files["api/src/main.ts"] == SCAFFOLD["api/src/main.ts"]
    assert "web/app/NoteForm.test.tsx" not in artifact.files
    # Hidden tests are prefixed by stage, so the two stages never collide.
    assert list(artifact.task.tests) == ["stage1-tags.test.ts"]
    assert list(artifact.change.tests) == ["stage2-filter.test.ts"]
    assert artifact.change_request_min == 25 and artifact.duration_min == 45
    assert static_problems(artifact) == []


def test_unreadable_submissions_say_what_is_wrong() -> None:
    data = _submit()
    del data["task"]["tests"]
    data["change_request"]["target_min"] = "twenty"
    data["files"] = [{"path": "../escape.ts", "content": "x"}, {"path": "a.ts"}]
    with pytest.raises(InvalidOutput) as caught:
        artifact_from_submit(data, _request(), SCAFFOLD)
    text = "\n".join(caught.value.problems)
    assert "task.tests must be a list" in text
    assert "change_request.target_min must be an integer" in text
    assert "must be a relative path" in text and "needs a string path and content" in text


def test_the_pack_lockfile_is_never_written_and_a_changed_gemfile_drops_it() -> None:
    request = _request(stack="rails")
    data = rails_tags.submit_input()
    assert "Gemfile.lock" in artifact_from_submit(data, request, RAILS_SCAFFOLD).files
    data["files"].append({"path": "Gemfile.lock", "content": "nope"})
    with pytest.raises(InvalidOutput, match="lockfile"):
        artifact_from_submit(data, request, RAILS_SCAFFOLD)
    data = rails_tags.submit_input()
    gemfile = RAILS_SCAFFOLD["Gemfile"] + 'gem "bcrypt", "3.1.22"\n'
    data["files"].append({"path": "Gemfile", "content": gemfile})
    assert "Gemfile.lock" not in artifact_from_submit(data, request, RAILS_SCAFFOLD).files


def test_a_revision_changes_only_what_it_sends() -> None:
    artifact = _artifact()
    revised = artifact_from_revise(
        {
            "files": [{"path": "web/app/Tags.tsx", "content": "export {}\n"}],
            "delete": ["web/app/globals.css"],
            "change_request": _submit()["change_request"] | {"title": "Filter notes"},
        },
        artifact,
        SCAFFOLD,
    )
    assert revised.files["web/app/Tags.tsx"] == "export {}\n"
    assert "web/app/globals.css" not in revised.files
    assert revised.change.title == "Filter notes" and revised.task == artifact.task
    assert revised.title == artifact.title and revised.analysis_hints == artifact.analysis_hints


# -- the rules code enforces -------------------------------------------------------


def _problems_after(change: Any) -> list[str]:
    data = _submit()
    change(data)
    return static_problems(artifact_from_submit(data, _request(), SCAFFOLD))


def test_browser_storage_in_app_code_is_refused_but_tests_may_mention_it() -> None:
    def storage(data: dict[str, Any]) -> None:
        data["files"].append(
            {"path": "web/app/Saved.tsx", "content": "localStorage.setItem('a', 'b');\n"}
        )
        data["task"]["reference"].append(
            {"path": "web/app/cookie.ts", "content": "document.cookie = 'x';\n"}
        )
        data["files"].append(
            {"path": "web/app/Saved.test.tsx", "content": "expect(localStorage).toBeDefined()\n"}
        )

    problems = _problems_after(storage)
    assert len(problems) == 2
    assert "baseline: web/app/Saved.tsx uses browser storage" in problems[0]
    assert "task reference: web/app/cookie.ts" in problems[1]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d.update(files=[], delete=["README.md"]), "needs a README.md"),
        (lambda d: d.update(delete=["web/app/page.tsx"]), None),
        (lambda d: d.update(open_path="nope.ts"), "open_path 'nope.ts' is not a project file"),
        (
            lambda d: d["task"]["tests"].append({"name": "x.spec.ts", "content": ""}),
            "must be a plain file name ending in .test.ts or .test.tsx",
        ),
        (
            lambda d: d["change_request"].update(
                reference=[{"path": SERVICE, "content": next_nest_tags.SERVICE_TAGS}]
            ),
            "The change_request reference changes nothing",
        ),
        (
            lambda d: d["files"].append({"path": "big.ts", "content": "x\n" * 2000}),
            "keep it under 1800",
        ),
        (
            lambda d: d["files"].append({"path": "node_modules/x/index.js", "content": ""}),
            "inside node_modules/",
        ),
    ],
)
def test_static_rules(change: Any, expected: str | None) -> None:
    try:
        problems = _problems_after(change)
    except InvalidOutput as exc:
        problems = exc.problems
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


# -- sandbox verdicts --------------------------------------------------------------


def _check(sandbox: RuleSandbox, artifact: Artifact) -> Any:
    return _check_steps(sandbox, artifact)[0]


def _check_steps(sandbox: RuleSandbox, artifact: Artifact) -> tuple[Any, list[tuple[str, str]]]:
    steps: list[tuple[str, str]] = []
    result = check_project(
        sandbox,
        artifact,
        sandbox_id="genchk-1",
        preview_base="/api/preview/genchk-1/tokentokentokentoken",
        step=lambda phase, detail: steps.append((phase, detail)),
        sleep=lambda _s: None,
    )
    return result, steps


def test_a_good_project_validates_and_records_each_stage_s_cases() -> None:
    sandbox = RuleSandbox()
    artifact = _artifact()
    result, steps = _check_steps(sandbox, artifact)
    assert result.ok, result.problems
    assert sandbox.sandboxes == {}  # Cleaned up.
    task_cases, change_cases = result.cases
    assert {name for _, name in task_cases} == {
        "task: tags > saves normalised tags",
        "task: tags > lists notes with their tags",
        "task: tags > rejects more than five tags",
    }
    assert {c for c, _ in change_cases} == {".dayline/hidden/stage2-filter.test.ts"}
    assert artifact.task.cases == [list(c) for c in task_cases]
    # Edge-case titles now point at recorded names; the made-up one is dropped.
    limit = next(e for e in artifact.task.edge_cases if e.id == "limit")
    assert limit.tests == ["task: tags > rejects more than five tags"]
    assert any("a test that does not exist" in note for note in result.notes)
    assert [p for p, _ in steps][:2] == ["checking_dependencies", "booting"]
    # The app's page was loaded through the preview.
    assert sandbox.preview_requests[0]["port"] == 3000


def _variant(**stage_changes: Any) -> Artifact:
    data = _submit()
    for key, value in stage_changes.items():
        stage, field = key.split("__")
        data[stage][field] = value
    return _artifact(data)


def test_a_broken_task_reference_fails_validation() -> None:
    broken = [{"path": SERVICE, "content": next_nest_tags.SERVICE_TAGS.replace("normalise(", "x(")}]
    result = _check(RuleSandbox(), _variant(task__reference=broken))
    assert not result.ok
    assert any("task's hidden tests must pass once" in p for p in result.problems)
    assert result.cases == ([], [])


def test_a_broken_change_reference_fails_validation() -> None:
    broken = [{"path": SERVICE, "content": next_nest_tags.SERVICE_TAGS + "// filter later\n"}]
    result = _check(RuleSandbox(), _variant(change_request__reference=broken))
    assert any("must pass once both reference solutions" in p for p in result.problems)
    assert any("must pass together" in p for p in result.problems)


def test_tests_that_already_pass_before_their_stage_fail_validation() -> None:
    artifact = _artifact()
    # The baseline already has the task, and the task's reference already filters.
    artifact.files[SERVICE] = next_nest_tags.SERVICE_TAGS
    artifact.task.reference[SERVICE] = next_nest_tags.SERVICE_FILTER
    result = _check(RuleSandbox(), artifact)
    assert any("already pass on the baseline" in p for p in result.problems)
    assert any("already pass with only the task's reference" in p for p in result.problems)


def test_failing_visible_tests_servers_and_preview_are_all_reported() -> None:
    sandbox = RuleSandbox()
    sandbox.next_report = {"status": "failed", "passed": 0, "failed": 1, "cases": [
        {"classname": "api/test/notes.test.ts", "name": "creates", "outcome": "failed",
         "message": "expected 201"},
    ]}  # fmt: skip
    sandbox.preview_reply = lambda _r: (500, [], b"Internal Server Error")
    result = _check(sandbox, _artifact())
    text = "\n".join(result.problems)
    assert "baseline's own tests must pass" in text and "expected 201" in text
    assert "answered HTTP 500" in text
    assert "visible tests must still pass" in text


def test_a_dev_server_that_exits_is_reported_with_its_log() -> None:
    class Exiting(RuleSandbox):
        def servers(self, sandbox_id: str) -> list[dict[str, Any]]:
            return [s | {"state": "exited"} for s in super().servers(sandbox_id)]

    sandbox = Exiting()
    result = _check(sandbox, _artifact())
    assert any("api dev server exited" in p and "api is ready" in p for p in result.problems)


def test_dependency_problems_stop_before_any_sandbox() -> None:
    class Strict(RuleSandbox):
        def check_dependencies(self, pack: str, files: dict[str, str]) -> list[str]:
            return ["web/package.json: lodash is not installed"]

    sandbox = Strict()
    result = _check(sandbox, _artifact())
    assert result.problems[0].startswith("Dependencies (baseline): web/package.json: lodash")
    assert sandbox.sandboxes == {} and sandbox.hidden_runs == []


def test_edge_titles_match_minitest_and_vitest_names() -> None:
    artifact = _artifact()
    spec = artifact.task
    spec.edge_cases[0].tests = ["Saves normalised tags"]
    map_edge_cases(spec, [("Stage1TagsTest", "test_saves_normalised_tags")])
    assert spec.edge_cases[0].tests == ["test_saves_normalised_tags"]


# -- generate: the repair loop -----------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.progress: list[tuple[str, int, str]] = []
        self.log: list[tuple[int, str, str]] = []
        self.cancel = False

    def hooks(self) -> Hooks:
        return Hooks(
            progress=lambda phase, attempt, detail: self.progress.append((phase, attempt, detail)),
            log=lambda attempt, kind, message: self.log.append((attempt, kind, message)),
            cancelled=lambda: self.cancel,
        )


def _generate(client: FakeAnthropic, recorder: Recorder, sandbox: Any = None) -> Any:
    return generate(
        client,  # type: ignore[arg-type]
        "test-model",
        sandbox or RuleSandbox(),
        _request(),
        SCAFFOLD,
        {"next": "16.4.6"},
        recorder.hooks(),
    )


def test_a_project_that_breaks_a_rule_is_repaired_with_only_what_changes() -> None:
    first = _submit()
    first["files"].append({"path": "web/app/Saved.tsx", "content": "localStorage.x = 1;\n"})
    messages = FakeMessages(
        [
            tool_reply(SUBMIT, first, "tu_a"),
            tool_reply(
                REVISE,
                {"files": [{"path": "web/app/Saved.tsx", "content": "export {};\n"}]},
                "tu_b",
            ),
        ]
    )
    recorder = Recorder()
    result = _generate(FakeAnthropic(messages), recorder)
    assert result.attempts == 2
    assert result.artifact.files["web/app/Saved.tsx"] == "export {};\n"
    assert [kind for _, kind, _ in recorder.log] == ["rules", "note", "validated"]
    # The second call answers the first tool call with the problems, as an error.
    feedback = messages.calls[1]["messages"][-1]["content"][0]
    assert feedback["type"] == "tool_result" and feedback["tool_use_id"] == "tu_a"
    assert feedback["is_error"] and "browser storage" in feedback["content"]
    assert "revise_project" in feedback["content"]
    # Prompt: the round, the stack's rules, the allowed list, and the scaffold.
    prompt = messages.calls[0]["messages"][0]["content"]
    assert "at 25 min they ask for filtering" in prompt and "next = 16.4.6" in prompt
    assert '<file path="api/src/main.ts">' in prompt
    assert result.usage.calls == 2 and result.usage.output_tokens == 1000
    phases = [p for p, _, _ in recorder.progress]
    assert phases[0] == "writing" and "repairing" in phases and phases[-1] == "running_tests"


def test_repairs_are_bounded_and_the_failure_keeps_every_attempt() -> None:
    broken = _submit()
    broken["change_request"]["reference"] = [
        {"path": SERVICE, "content": next_nest_tags.SERVICE_TAGS + "// todo\n"}
    ]
    still_broken = {"change_request": copy.deepcopy(broken["change_request"])}
    replies = [tool_reply(SUBMIT, broken, "tu_0")] + [
        tool_reply(REVISE, still_broken, f"tu_{i}") for i in range(1, project_gen.MAX_REPAIRS + 1)
    ]
    messages = FakeMessages(replies)
    recorder = Recorder()
    sandbox = RuleSandbox()
    with pytest.raises(GenerationFailed, match="after 3 repair attempts"):
        _generate(FakeAnthropic(messages), recorder, sandbox)
    assert len(messages.calls) == 1 + project_gen.MAX_REPAIRS
    assert [(a, kind) for a, kind, _ in recorder.log] == [(i, "sandbox") for i in range(4)]
    assert "must pass once both reference solutions" in recorder.log[-1][2]
    assert sandbox.sandboxes == {}


def test_unreadable_output_is_sent_back_and_a_full_project_is_asked_for() -> None:
    bad = _submit()
    del bad["task"]
    messages = FakeMessages(
        [tool_reply(SUBMIT, bad, "tu_a"), tool_reply(SUBMIT, _submit(), "tu_b")]
    )
    recorder = Recorder()
    result = _generate(FakeAnthropic(messages), recorder)
    assert result.attempts == 2 and recorder.log[0][1] == "invalid"
    feedback = messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert (
        "task must be an object" in feedback and "submit_project with the full project" in feedback
    )


def test_a_reply_without_the_tool_is_nudged_once() -> None:
    messages = FakeMessages([text_reply("Here is my plan..."), tool_reply(SUBMIT, _submit())])
    result = _generate(FakeAnthropic(messages), Recorder())
    assert result.attempts == 1
    assert messages.calls[1]["messages"][-1] == {
        "role": "user",
        "content": "Respond only by calling the submit_project tool.",
    }
    tools = [t["name"] for t in messages.calls[0]["tools"]]
    assert tools == [SUBMIT, REVISE] and messages.calls[0]["output_config"] == {"effort": "medium"}


def test_a_model_that_never_calls_the_tool_fails_clearly() -> None:
    messages = FakeMessages([text_reply("No."), text_reply("Still no.")])
    with pytest.raises(GenerationFailed, match="did not return a project"):
        _generate(FakeAnthropic(messages), Recorder())


def test_cancelling_stops_mid_stream() -> None:
    recorder = Recorder()
    messages = FakeMessages([tool_reply(SUBMIT, _submit())])

    def cancel_on_first_event(_event: Any) -> None:
        recorder.cancel = True

    messages.before_event = cancel_on_first_event
    usage = Usage()
    with pytest.raises(Cancelled):
        generate(
            FakeAnthropic(messages),  # type: ignore[arg-type]
            "m",
            RuleSandbox(),
            _request(),
            SCAFFOLD,
            {},
            recorder.hooks(),
            usage,
        )


# -- the staged problem ------------------------------------------------------------


def test_a_validated_project_becomes_a_two_stage_ai_assisted_problem() -> None:
    artifact = _artifact()
    result = _check(RuleSandbox(), artifact)
    stored = Artifact.from_json(artifact.to_json())
    problem = staged_problem("proj-1", stored)
    assert problem.round_type is MockRoundType.AI_ASSISTED_PROJECT
    assert problem.pack == "next-nest" and problem.starter == artifact.files
    assert [s.slug for s in problem.stages] == ["task", "change-request"]
    assert problem.stages[1].unlock_min == 25 and problem.stages[0].target_min == 25
    assert problem.solution == (
        "api/src/notes/create-note.dto.ts",
        "api/src/notes/notes.controller.ts",
        "api/src/notes/notes.service.ts",
    )
    assert problem.analysis_hints == tuple(artifact.analysis_hints)
    assert problem.overview_md == next_nest_tags.README
    assert problem.stages[0].test_names == {n for _, n in result.cases[0]}

    # A round: stage 1's tests gate stage 1; then both stages' tests run.
    sandbox = RuleSandbox()
    sandbox.create("s", "next-nest", artifact.files)
    attempts = [StageAttempt(status=StageStatus.ACTIVE), StageAttempt()]
    assert set(staged.hidden_files(problem, attempts)) == {"stage1-tags.test.ts"}
    run = sandbox.run_hidden_tests("s", staged.hidden_files(problem, attempts))
    assert staged.record_run(problem, attempts, run) is False
    sandbox.write_file("s", SERVICE, next_nest_tags.SERVICE_TAGS, None)
    run = sandbox.run_hidden_tests("s", staged.hidden_files(problem, attempts))
    assert staged.record_run(problem, attempts, run) is True
    staged.finish_stage(attempts, StageStatus.PASSED, {}, attempts[0].started_at or _now())
    assert len(staged.hidden_files(problem, attempts)) == 2
    run = sandbox.run_hidden_tests("s", staged.hidden_files(problem, attempts))
    assert staged.record_run(problem, attempts, run) is False
    assert set(attempts[1].first_outcomes) == problem.stages[1].test_names


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)
