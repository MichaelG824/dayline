"""Live mock sessions: practise on a real repo in a sandbox.

A live session is a :class:`~dayline.models.MockSession` with ``kind=live``
whose sandbox (same id) lives in the sandbox runner. This module starts it
from a built-in template, proxies file and test calls to the runner while
recording events (saves, test runs), and ends it by saving the final files and
the diff against the template. Grading then works like any other session
(``services/mock.py``), with the work record standing in for, or alongside,
a transcript.

A staged round (``services/mock_staged.py``) is a live session too, so its
files, terminal, and ending all go through here.
"""

from __future__ import annotations

import contextlib
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from dayline.adapters.sandbox import (
    SandboxClient,
    SandboxRequestError,
    SandboxUnavailable,
    TerminalConnection,
)
from dayline.api.context import AppContext
from dayline.api.services.mock import _get_session, check_session_refs
from dayline.api.services.staged_clock import catch_up
from dayline.api.services.staged_problems import session_problem
from dayline.mock import staged
from dayline.mock.templates import builtin_templates
from dayline.mock.worklog import chat_transcript, line_changes, repo_diff, save_diff
from dayline.models import (
    MockEvent,
    MockEventKind,
    MockSession,
    MockSessionKind,
    MockSessionStatus,
)

# Where the browser previews a session's dev servers (services/mock_preview.py).
PREVIEW_PREFIX = "/api/preview"


def new_preview_base(session_id: str) -> str:
    """A fresh preview base for a new session's sandbox: the path, with an
    unguessable token, that its dev servers are previewed under."""
    return f"{PREVIEW_PREFIX}/{session_id}/{secrets.token_urlsafe(24)}"


@contextlib.contextmanager
def runner_errors() -> Iterator[None]:
    """Turn runner failures into HTTP errors the UI can show as-is."""
    try:
        yield
    except SandboxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SandboxRequestError as exc:
        if exc.status_code == 401:
            raise HTTPException(
                status_code=502,
                detail="Dayline and the sandbox runner have different SANDBOX_RUNNER_SECRETs",
            ) from exc
        status = exc.status_code if 400 <= exc.status_code < 500 or exc.status_code == 503 else 502
        raise HTTPException(status_code=status, detail=exc.detail) from exc


def sandbox_client(ctx: AppContext) -> SandboxClient:
    if ctx.sandbox is None:
        raise HTTPException(
            status_code=503,
            detail="Live sessions need the sandbox runner (set SANDBOX_RUNNER_URL).",
        )
    return ctx.sandbox


def live_session(ctx: AppContext, session_id: str) -> MockSession:
    """A live session that has not ended yet, or a 404/409."""
    session = _get_session(ctx, session_id)
    if session.kind is not MockSessionKind.LIVE:
        raise HTTPException(status_code=404, detail="Not a live session")
    if session.status is not MockSessionStatus.LIVE:
        raise HTTPException(status_code=409, detail="This session has ended")
    return session


def event(ctx: AppContext, session_id: str, kind: MockEventKind, **data: Any) -> None:
    ctx.mock_source.add_event(MockEvent(session_id=session_id, kind=kind, data=data))


def starting_files(ctx: AppContext, session: MockSession) -> dict[str, str] | None:
    """The files the session's sandbox started with (``None`` if its
    template or staged problem no longer exists)."""
    if session.staged_problem_id:
        problem = session_problem(ctx, session)
        return problem.starter if problem else None
    template = builtin_templates().get(session.template_id or "")
    return template.files if template else None


def availability(ctx: AppContext) -> dict[str, Any]:
    """Whether live sessions can start, and the templates and staged
    problems to pick from."""
    templates = [
        {
            "id": t.id,
            "title": t.title,
            "pack": t.pack,
            "roundType": t.round_type.value,
            "durationMin": t.duration_min,
            "summary": t.summary,
        }
        for t in builtin_templates().values()
    ]
    packs: list[dict[str, Any]] = []
    reason = None
    if ctx.sandbox is None:
        reason = "Live sessions need the sandbox runner (set SANDBOX_RUNNER_URL)."
    else:
        try:
            packs = ctx.sandbox.packs()
        except (SandboxUnavailable, SandboxRequestError) as exc:
            reason = str(exc)
    staged_problems = [
        {
            "id": p.id,
            "title": p.title,
            "pack": p.pack,
            "roundType": p.round_type.value,
            "durationMin": p.duration_min,
            "summary": p.summary,
            "stageCount": len(p.stages),
        }
        for p in staged.builtin_staged_problems().values()
    ]
    return {
        "available": reason is None,
        "reason": reason,
        "templates": templates,
        "stagedProblems": staged_problems,
        "packs": packs,
    }


def start_session(
    ctx: AppContext,
    template_id: str,
    question_id: str | None,
    rubric_id: str | None,
    guideline_id: str | None,
) -> str:
    """Create the session and its sandbox; returns the session id. If the
    sandbox cannot start, the session is not kept."""
    sandbox = sandbox_client(ctx)
    template = builtin_templates().get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"No template {template_id!r}")
    check_session_refs(ctx, question_id, rubric_id, guideline_id)

    now = datetime.now(UTC)
    session = ctx.mock_source.create_session(
        MockSession(
            id=str(uuid.uuid4()),
            title=template.title,
            question_id=question_id or None,
            rubric_id=rubric_id or None,
            guideline_id=guideline_id or None,
            kind=MockSessionKind.LIVE,
            status=MockSessionStatus.LIVE,
            template_id=template.id,
            pack=template.pack,
            started_at=now,
        )
    )
    try:
        with runner_errors():
            sandbox.create(
                session.id, template.pack, template.files, new_preview_base(session.id)
            )
    except HTTPException:
        ctx.mock_source.delete_session(session.id)
        raise
    event(ctx, session.id, MockEventKind.SESSION_STARTED, template=template.id)
    return session.id


def sandbox_status(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """The sandbox's state for the workspace header: ``running``, ``stopped``
    (idle or out of time; files are kept), or ``gone``."""
    live_session(ctx, session_id)
    sandbox = sandbox_client(ctx)
    try:
        with runner_errors():
            info = sandbox.info(session_id)
            packs = sandbox.packs()
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"state": "gone", "editorLanguage": None}
        raise
    language = next((p["editorLanguage"] for p in packs if p["name"] == info["pack"]), None)
    return {
        "state": info["state"],
        "expiresAt": datetime.fromtimestamp(info["expiresAt"], UTC).isoformat(),
        "idleTimeoutS": info["idleTimeoutS"],
        "editorLanguage": language or info["pack"],
    }


def resume(ctx: AppContext, session_id: str) -> dict[str, Any]:
    live_session(ctx, session_id)
    with runner_errors():
        sandbox_client(ctx).resume(session_id)
    return sandbox_status(ctx, session_id)


def list_files(ctx: AppContext, session_id: str) -> list[dict[str, Any]]:
    live_session(ctx, session_id)
    with runner_errors():
        return sandbox_client(ctx).list_files(session_id)


def read_file(ctx: AppContext, session_id: str, path: str) -> dict[str, Any]:
    live_session(ctx, session_id)
    with runner_errors():
        return sandbox_client(ctx).read_file(session_id, path)


def write_file(
    ctx: AppContext, session_id: str, path: str, content: str, base_version: str | None
) -> dict[str, Any]:
    """Save a file. ``base_version`` is the version the editor loaded (``""``
    for a new file); a file changed since (say, from the terminal) is a 409."""
    live_session(ctx, session_id)
    sandbox = sandbox_client(ctx)
    with runner_errors():
        try:
            before: str | None = sandbox.read_file(session_id, path)["content"]
        except SandboxRequestError as exc:
            if exc.status_code != 404:
                raise
            before = None
        result = sandbox.write_file(session_id, path, content, base_version)
    added, removed = line_changes(before, content)
    if added or removed or before is None:
        event(
            ctx,
            session_id,
            MockEventKind.FILE_SAVED,
            path=path,
            added=added,
            removed=removed,
            diff=save_diff(path, before, content),
        )
    return result


def run_tests(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Run the pack's test command; the report is kept as the session's last run."""
    session = live_session(ctx, session_id)
    with runner_errors():
        report = sandbox_client(ctx).run_tests(session_id)
    session.test_report = report
    ctx.mock_source.update_session(session)
    event(
        ctx,
        session_id,
        MockEventKind.TESTS_RUN,
        status=report.get("status"),
        passed=report.get("passed", 0),
        failed=report.get("failed", 0),
        errors=report.get("errors", 0),
    )
    return report


def end_session(ctx: AppContext, session_id: str) -> None:
    """Save the final files, the diff, and the terminal's commands (as
    events at the time each ran), then delete the sandbox. Ending twice
    is a no-op. If the runner is unreachable nothing changes, so it can be
    retried; if the sandbox is already gone the session ends without files."""
    session = _get_session(ctx, session_id)
    if session.kind is not MockSessionKind.LIVE or session.status is MockSessionStatus.ENDED:
        return
    sandbox = sandbox_client(ctx)
    lost = False
    try:
        with runner_errors():
            files: dict[str, str] = sandbox.snapshot(session_id)["files"]
            commands = sandbox.commands(session_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        files, commands, lost = {}, [], True
    for run in commands:
        ctx.mock_source.add_event(
            MockEvent(
                session_id=session_id,
                kind=MockEventKind.COMMAND_RUN,
                data={"command": run["command"], "exitCode": run["exitCode"]},
                at=datetime.fromtimestamp(run["at"], UTC),
            )
        )

    start = starting_files(ctx, session)
    now = datetime.now(UTC)
    problem = session_problem(ctx, session)
    if problem is not None:
        # A change request that came due while nobody was looking still came.
        catch_up(ctx, session, problem, now)
    session.final_files = files
    session.final_diff = "" if lost or start is None else repo_diff(start, files)
    session.status = MockSessionStatus.ENDED
    session.ended_at = now
    if problem is not None:
        staged.close_round(session.stages, staged.solution_files(problem, files), now)
        # The interviewer chat is the round's transcript, for grading.
        events = ctx.mock_source.list_events(session_id)
        session.transcript = chat_transcript(events, session.started_at)
    ctx.mock_source.update_session(session)
    event(ctx, session_id, MockEventKind.SESSION_ENDED, sandboxLost=lost)
    with contextlib.suppress(SandboxUnavailable, SandboxRequestError):
        sandbox.destroy(session_id)


def open_terminal(
    ctx: AppContext, session_id: str, cols: int, rows: int
) -> contextlib.AbstractAsyncContextManager[TerminalConnection]:
    """The session's shell. Checks the session first (raising HTTPException);
    connecting can raise :class:`SandboxUnavailable`."""
    live_session(ctx, session_id)
    return sandbox_client(ctx).open_terminal(session_id, cols, rows)
