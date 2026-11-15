"""Validating a generated project in a real sandbox before anyone sees it.

A generated :class:`~dayline.mock.project_spec.Artifact` is only handed over
once every check here passes in a fresh sandbox of its stack's pack:

1. its dependencies stay within the pack's allowed list (baseline, and with
   each reference applied);
2. the baseline's dev servers boot to ready and the app answers through the
   preview proxy;
3. the baseline's own (visible) tests pass;
4. the task's hidden tests FAIL on the baseline and PASS once the task's
   reference is applied;
5. the change request's hidden tests FAIL with only the task's reference and
   PASS once its own reference is applied on top, together with the task's
   tests, and the visible tests still pass.

Problems are collected rather than stopping at the first, so one repair
round can fix several. The passing runs also record which JUnit cases belong
to which stage (``StageSpec.cases``), which is how a round later tells the
two stages' results apart in any test language.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dayline.adapters.sandbox import SandboxClient, SandboxRequestError, SandboxUnavailable
from dayline.mock.project_spec import STACKS, Artifact, StageSpec

SERVER_READY_TIMEOUT_S = 300.0
_POLL_S = 2.0
_STEP_EVERY_S = 10.0
_FAILING_CASES_SHOWN = 6
_MESSAGE_CHARS = 700
_OUTPUT_CHARS = 2500
_LOG_LINES = 40

Case = tuple[str, str]
Step = Callable[[str, str], None]


class Cancelled(Exception):
    """The candidate cancelled the generation."""


@dataclass(slots=True)
class CheckResult:
    problems: list[str] = field(default_factory=list)
    # Each stage's hidden test cases, recorded from the passing runs.
    cases: tuple[list[Case], list[Case]] = ([], [])
    # What the edge-case mapping had to drop (not a failure).
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def report_summary(report: dict[str, Any]) -> str:
    """A test run as the model needs it to fix things: the counts, the
    failing cases with their messages, and the output when nothing ran."""
    head = (
        f"status {report.get('status')}: {report.get('passed', 0)} passed, "
        f"{report.get('failed', 0)} failed, {report.get('errors', 0)} errors"
    )
    cases = [c for c in report.get("cases") or [] if c.get("outcome") in ("failed", "error")]
    lines = [head]
    for case in cases[:_FAILING_CASES_SHOWN]:
        message = str(case.get("message") or "").strip()[:_MESSAGE_CHARS]
        lines.append(f"- {case.get('classname')} > {case.get('name')}: {message}")
    if len(cases) > _FAILING_CASES_SHOWN:
        lines.append(f"- ...and {len(cases) - _FAILING_CASES_SHOWN} more failing")
    if not cases:
        output = str(report.get("output") or "").strip()
        if output:
            lines.append("Output (end):\n" + output[-_OUTPUT_CHARS:])
    return "\n".join(lines)


def _cases(report: dict[str, Any]) -> list[Case]:
    return sorted(
        {(str(c.get("classname") or ""), str(c.get("name") or "")) for c in report["cases"]}
    )


def _normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_").removeprefix("test_")


def map_edge_cases(spec: StageSpec, cases: list[Case]) -> list[str]:
    """Point each edge case at the recorded test names its titles name (the
    model writes titles; Minitest reports ``test_<title>``, Vitest
    ``<describe> > <title>``). Titles that match nothing are dropped, and an
    edge case left with no tests is dropped; returns what was dropped."""
    names = sorted({name for _, name in cases})
    dropped: list[str] = []
    kept = []
    for edge in spec.edge_cases:
        matched: list[str] = []
        for title in edge.tests:
            want = _normal(title)
            hits = [
                n for n in names if want and (_normal(n) == want or _normal(n).endswith("_" + want))
            ]
            if hits:
                matched += [h for h in hits if h not in matched]
            else:
                dropped.append(f"edge case {edge.id}: no hidden test named {title!r}")
        if matched:
            edge.tests = matched
            kept.append(edge)
        else:
            dropped.append(f"edge case {edge.id} dropped: none of its tests ran")
    spec.edge_cases = kept
    return dropped


class _Run:
    """One validation in one sandbox (``check_project``'s state)."""

    def __init__(
        self,
        sandbox: SandboxClient,
        artifact: Artifact,
        sandbox_id: str,
        step: Step,
        cancelled: Callable[[], bool],
        sleep: Callable[[float], None],
        clock: Callable[[], float],
    ) -> None:
        self.sandbox = sandbox
        self.artifact = artifact
        self.id = sandbox_id
        self.step = step
        self.cancelled = cancelled
        self.sleep = sleep
        self.clock = clock
        self.problems: list[str] = []

    def check_cancel(self) -> None:
        if self.cancelled():
            raise Cancelled

    def logs_tail(self, server: str) -> str:
        try:
            lines = self.sandbox.server_logs(self.id, server, 0)["lines"]
        except (SandboxUnavailable, SandboxRequestError):
            return ""
        return "\n".join(lines[-_LOG_LINES:])

    def wait_for_servers(self) -> list[dict[str, Any]]:
        """Wait until every dev server is ready; problems for any that exit
        or never get there."""
        start = last_step = self.clock()
        while True:
            self.check_cancel()
            servers = self.sandbox.servers(self.id)
            states = {s["name"]: s["state"] for s in servers}
            if all(state == "ready" for state in states.values()):
                return servers
            for name, state in states.items():
                if state == "exited":
                    self.problems.append(
                        f"The {name} dev server exited while starting. Its log ends:\n"
                        + self.logs_tail(name)
                    )
            if any(state == "exited" for state in states.values()):
                return []
            waited = self.clock() - start
            if waited > SERVER_READY_TIMEOUT_S:
                slow = [n for n, s in states.items() if s != "ready"]
                for name in slow:
                    self.problems.append(
                        f"The {name} dev server was not ready after "
                        f"{int(SERVER_READY_TIMEOUT_S)}s. Its log ends:\n" + self.logs_tail(name)
                    )
                return []
            if self.clock() - last_step >= _STEP_EVERY_S:
                pending = ", ".join(n for n, s in states.items() if s != "ready")
                self.step("booting", f"Waiting for {pending} to start ({int(waited)}s)")
                last_step = self.clock()
            self.sleep(_POLL_S)

    def check_preview(self, servers: list[dict[str, Any]], base: str) -> None:
        """The app's page answers through the preview proxy."""
        web = next((s for s in servers if s["name"] == "web"), servers[0] if servers else None)
        if web is None:
            return
        self.step("booting", "Loading the app through the preview")
        try:
            status, body = self.sandbox.fetch_preview(self.id, base, int(web["port"]), "")
        except SandboxRequestError as exc:
            self.problems.append(f"The preview could not load the app: {exc.detail}")
            return
        if status >= 400:
            self.problems.append(
                f"The app's home page answered HTTP {status} in the preview. Body (start):\n"
                f"{body[:1500]}\n{web['name']} log ends:\n{self.logs_tail(str(web['name']))}"
            )

    def hidden(self, files: dict[str, str], label: str) -> dict[str, Any]:
        self.check_cancel()
        self.step("running_tests", label)
        return self.sandbox.run_hidden_tests(self.id, files)

    def write(self, files: dict[str, str]) -> None:
        for path, content in files.items():
            self.sandbox.write_file(self.id, path, content, None)


def check_project(
    sandbox: SandboxClient,
    artifact: Artifact,
    *,
    sandbox_id: str,
    preview_base: str,
    step: Step,
    cancelled: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> CheckResult:
    """Validate ``artifact`` in a new sandbox ``sandbox_id`` (destroyed
    afterwards). ``step(phase, detail)`` reports progress; phases are
    ``checking_dependencies``, ``booting`` and ``running_tests``. Raises
    :class:`Cancelled`, and lets runner outages
    (:class:`~dayline.adapters.sandbox.SandboxUnavailable`) through."""
    pack = STACKS[artifact.stack].pack
    task, change = artifact.task, artifact.change
    run = _Run(sandbox, artifact, sandbox_id, step, cancelled, sleep, clock)

    step("checking_dependencies", "Checking dependencies against the stack's allowed list")
    for label, files in (
        ("baseline", artifact.files),
        ("with the task reference", artifact.after(1)),
        ("with the change-request reference", artifact.after(2)),
    ):
        found = sandbox.check_dependencies(pack, files)
        run.problems += [f"Dependencies ({label}): {p}" for p in found]
    if run.problems:
        return CheckResult(problems=run.problems)

    run.check_cancel()
    step("booting", "Starting a sandbox with the baseline")
    try:
        sandbox.create(sandbox_id, pack, artifact.files, preview_base)
    except SandboxRequestError as exc:
        if exc.status_code in (409, 503):  # Busy or not ready: not the project's fault.
            raise
        return CheckResult(problems=[f"The sandbox refused the project: {exc.detail}"])
    try:
        servers = run.wait_for_servers()
        if servers:
            run.check_preview(servers, preview_base)

        run.check_cancel()
        step("running_tests", "Visible tests on the baseline (should pass)")
        report = sandbox.run_tests(sandbox_id)
        if report.get("status") != "passed":
            run.problems.append(
                "The baseline's own tests must pass (and at least one must exist):\n"
                + report_summary(report)
            )

        report = run.hidden(task.tests, "Task tests on the baseline (should fail)")
        if report.get("status") == "passed":
            run.problems.append(
                "The task's hidden tests already pass on the baseline: the baseline must not "
                "implement the task, and the tests must check what the task adds."
            )

        run.write(task.reference)
        report = run.hidden(task.tests, "Task tests with the task's reference (should pass)")
        task_cases: list[Case] = []
        if report.get("status") == "passed":
            task_cases = _cases(report)
        else:
            run.problems.append(
                "The task's hidden tests must pass once the task's reference solution is "
                "applied:\n" + report_summary(report)
            )

        report = run.hidden(
            change.tests, "Change-request tests with only the task's reference (should fail)"
        )
        if report.get("status") == "passed":
            run.problems.append(
                "The change request's hidden tests already pass with only the task's "
                "reference: they must check what the change request adds."
            )

        run.write(change.reference)
        report = run.hidden(change.tests, "Change-request tests with both references (should pass)")
        change_cases: list[Case] = []
        if report.get("status") == "passed":
            change_cases = _cases(report)
        else:
            run.problems.append(
                "The change request's hidden tests must pass once both reference solutions "
                "are applied:\n" + report_summary(report)
            )

        report = run.hidden(
            {**task.tests, **change.tests}, "All hidden tests with both references (should pass)"
        )
        if report.get("status") != "passed":
            run.problems.append(
                "The task's and the change request's hidden tests must pass together once "
                "both references are applied (the change request must not break the task):\n"
                + report_summary(report)
            )
        elif task_cases and change_cases:
            overlap = set(task_cases) & set(change_cases)
            if overlap:
                run.problems.append(
                    "The task's and the change request's hidden tests must have different "
                    f"names (test class/describe plus title); both stages have {sorted(overlap)}"
                )
            elif set(_cases(report)) != set(task_cases) | set(change_cases):
                run.problems.append(
                    "Run together, the hidden tests are not the same cases as run per stage: "
                    "give each stage's tests their own test class or describe block."
                )

        run.check_cancel()
        step("running_tests", "Visible tests with both references (should pass)")
        report = sandbox.run_tests(sandbox_id)
        if report.get("status") != "passed":
            run.problems.append(
                "The visible tests must still pass once both references are applied (update "
                "or extend them in the references):\n" + report_summary(report)
            )
    finally:
        # The runner's reaper removes anything left behind.
        with contextlib.suppress(SandboxUnavailable, SandboxRequestError):
            sandbox.destroy(sandbox_id)

    if run.problems:
        return CheckResult(problems=run.problems)
    notes = map_edge_cases(task, task_cases) + map_edge_cases(change, change_cases)
    task.cases = [list(c) for c in task_cases]
    change.cases = [list(c) for c in change_cases]
    return CheckResult(cases=(task_cases, change_cases), notes=notes)
