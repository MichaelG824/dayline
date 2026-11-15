"""Generated practice projects: generate one in the background, follow its
progress, preview it, and start a round in it (``mock/project_gen.py``).

**Generation runs in a thread, its state in the database.** Writing and
validating a project takes minutes, longer than a request should. The
worker writes its phase, attempt log, and token usage to the project's row
as it goes, so a reloaded page picks up where it was. The browser follows
along with a long poll (``wait_project``): an open request keeps a
scale-to-zero host's CPU allocated while the worker runs. A row still
``generating`` that nobody has touched for :data:`STALE_AFTER` (the process
died) reads as failed.

Cancelling sets the worker's flag when the worker is in this process, and
marks the row cancelled either way; a worker in another process notices at
its next write (it re-reads the row before every write and never overwrites
a status it did not set).

**One generation per user at a time** (:func:`create_project` refuses a
second while one runs).

**Previewing** uses a sandbox of its own (``gen-<project id>``), started on
demand from the validated baseline and destroyed when the round starts or
the project is deleted; the runner's reaper stops an abandoned one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import anthropic
from fastapi import HTTPException

from dayline.adapters.sandbox import SandboxRequestError, SandboxUnavailable
from dayline.api.context import AppContext
from dayline.api.serializers import generated_project_json
from dayline.api.services import mock_staged, staged_problems
from dayline.api.services.mock_live import new_preview_base, runner_errors, sandbox_client
from dayline.api.services.mock_preview import SERVER_ACTIONS
from dayline.mock import generator_model
from dayline.mock.project_check import Cancelled
from dayline.mock.project_gen import GenerationFailed, Hooks, Usage, generate
from dayline.mock.project_spec import (
    STACKS,
    Artifact,
    GenerationRequest,
    RequestError,
    parse_request,
)
from dayline.mock.templates import builtin_templates
from dayline.models import GeneratedProject, GenerationStatus

log = logging.getLogger(__name__)

# A generating row untouched this long belongs to a process that died. The
# worker writes at least every few seconds while the model streams, and the
# longest silent step (a test run) is bounded by the runner's 300s cap.
STALE_AFTER = timedelta(minutes=10)
MAX_WAIT_S = 25.0
_WAIT_TICK_S = 0.25
# Progress writes are throttled; phase changes always write.
_WRITE_EVERY_S = 3.0
STOPPED = "Generation stopped unexpectedly (the server restarted). Regenerate to try again."


@dataclass(slots=True)
class _Job:
    """A generation running in this process."""

    cancel: threading.Event = field(default_factory=threading.Event)
    # Bumped on every progress change; long polls wait for it to move.
    version: int = 0
    done: bool = False


_jobs: dict[str, _Job] = {}
_create_lock = threading.Lock()


def _not_found(project_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No generated project {project_id!r}")


def _sweep(ctx: AppContext, project: GeneratedProject) -> GeneratedProject:
    """A generating row whose worker is gone reads (and is saved) as failed."""
    if project.status is not GenerationStatus.GENERATING or project.id in _jobs:
        return project
    touched = project.updated_at or project.created_at
    if touched is None or datetime.now(UTC) - touched < STALE_AFTER:
        return project
    project.status, project.error = GenerationStatus.FAILED, STOPPED
    project.finished_at = datetime.now(UTC)
    with contextlib.suppress(KeyError):
        return ctx.generated_source.update(project)
    return project


def _get(ctx: AppContext, owner: str, project_id: str) -> GeneratedProject:
    try:
        return _sweep(ctx, ctx.generated_source.get(owner, project_id))
    except KeyError as exc:
        raise _not_found(project_id) from exc


def _json(project: GeneratedProject) -> dict[str, Any]:
    job = _jobs.get(project.id)
    return generated_project_json(project) | {"version": job.version if job else None}


def list_projects(ctx: AppContext, owner: str) -> list[dict[str, Any]]:
    projects = [_sweep(ctx, p) for p in ctx.generated_source.list_projects(owner)]
    return [generated_project_json(p, detail=False) for p in projects]


def get_project(ctx: AppContext, owner: str, project_id: str) -> dict[str, Any]:
    return _json(_get(ctx, owner, project_id))


async def wait_project(
    ctx: AppContext, owner: str, project_id: str, version: int | None, wait_s: float
) -> dict[str, Any]:
    """The project, once its progress moves past ``version`` (a long poll,
    up to ``wait_s``). Returns at once when the worker is not in this process
    (``version`` is then ``None``; the client polls on a timer)."""
    job = _jobs.get(project_id)
    if job is not None and version is not None:
        deadline = time.monotonic() + min(max(wait_s, 0.0), MAX_WAIT_S)
        while job.version == version and not job.done and time.monotonic() < deadline:
            await asyncio.sleep(_WAIT_TICK_S)
    return await asyncio.to_thread(get_project, ctx, owner, project_id)


# --------------------------------------------------------------------------- #
# Generating
# --------------------------------------------------------------------------- #


def _check_ready_to_generate(ctx: AppContext, owner: str, stack: str) -> None:
    sandbox = sandbox_client(ctx)
    with runner_errors():
        packs = {p["name"]: p for p in sandbox.packs()}
    pack = packs.get(STACKS[stack].pack)
    if pack is None:
        raise HTTPException(
            status_code=503,
            detail="The sandbox runner has no full-stack packs yet: redeploy it.",
        )
    if pack.get("state") != "ready":
        raise HTTPException(
            status_code=503,
            detail=f"The {pack['displayName']} sandbox image is still being built. Try again soon.",
        )
    busy = [
        p
        for p in ctx.generated_source.list_projects(owner)
        if _sweep(ctx, p).status is GenerationStatus.GENERATING
    ]
    if busy:
        raise HTTPException(
            status_code=409,
            detail="A project is already being generated. Wait for it, or cancel it first.",
        )


def _start(
    ctx: AppContext,
    owner: str,
    request: GenerationRequest,
    context_files: list[dict[str, str]],
    parent_id: str | None,
) -> dict[str, Any]:
    with _create_lock:
        _check_ready_to_generate(ctx, owner, request.stack)
        project = ctx.generated_source.create(
            GeneratedProject(
                id=str(uuid.uuid4()),
                owner=owner,
                request=request.to_json(),
                context_files=context_files,
                progress={"phase": "writing", "attempt": 0, "detail": "Starting"},
                parent_id=parent_id,
            )
        )
        job = _Job()
        _jobs[project.id] = job
    threading.Thread(
        target=_work,
        args=(ctx, project, request, job),
        name=f"generate-{project.id[:8]}",
        daemon=True,
    ).start()
    return _json(project)


def create_project(
    ctx: AppContext,
    owner: str,
    *,
    prompt: str,
    stack: str,
    difficulty: str,
    duration_min: int,
    change_request_min: int,
    context_files: list[tuple[str, str]],
) -> dict[str, Any]:
    """Validate the inputs and start generating; returns the new project."""
    try:
        request = parse_request(
            prompt=prompt,
            stack=stack,
            difficulty=difficulty,
            duration_min=duration_min,
            change_request_min=change_request_min,
            context_files=context_files,
        )
    except RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    files = [{"name": f.name, "content": f.content} for f in request.context_files]
    return _start(ctx, owner, request, files, None)


def regenerate(ctx: AppContext, owner: str, project_id: str, feedback: str) -> dict[str, Any]:
    """A new generation with the same inputs (plus feedback). If the old
    project was ready, it is replaced once the new one is."""
    old = _get(ctx, owner, project_id)
    if old.status is GenerationStatus.GENERATING:
        raise HTTPException(status_code=409, detail="This project is still being generated")
    previous = Artifact.from_json(old.artifact) if old.artifact else None
    r = old.request
    try:
        request = parse_request(
            prompt=str(r.get("prompt", "")),
            stack=str(r.get("stack", "")),
            difficulty=str(r.get("difficulty", "")),
            duration_min=int(r.get("durationMin", 0)),
            change_request_min=int(r.get("changeRequestMin", 0)),
            context_files=[(f["name"], f["content"]) for f in old.context_files],
            feedback=feedback,
            previous=previous,
        )
    except RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parent = old.id if old.status is GenerationStatus.READY else None
    return _start(ctx, owner, request, old.context_files, parent)


def cancel(ctx: AppContext, owner: str, project_id: str) -> dict[str, Any]:
    project = _get(ctx, owner, project_id)
    if project.status is not GenerationStatus.GENERATING:
        return _json(project)
    job = _jobs.get(project_id)
    if job is not None:
        job.cancel.set()
    project.status, project.error = GenerationStatus.CANCELLED, "Cancelled"
    project.finished_at = datetime.now(UTC)
    project.progress = {**project.progress, "detail": "Cancelled"}
    return _json(ctx.generated_source.update(project))


def _sessions_using(ctx: AppContext, project_id: str) -> bool:
    return any(s.staged_problem_id == project_id for s in ctx.mock_source.list_sessions())


def delete_project(ctx: AppContext, owner: str, project_id: str) -> None:
    try:
        project = ctx.generated_source.get(owner, project_id)
    except KeyError:
        return
    if _sessions_using(ctx, project_id):
        raise HTTPException(
            status_code=409,
            detail="A practice session uses this project. Delete that session first.",
        )
    job = _jobs.get(project_id)
    if job is not None:
        job.cancel.set()
    _destroy_preview(ctx, project.id)
    staged_problems.forget(project_id)
    ctx.generated_source.delete(owner, project_id)


class _Reporter:
    """The worker's writes to the project row. It re-reads the row before
    each write and stops (raising :class:`Cancelled`) once the row is no
    longer generating: cancelled, deleted, or swept."""

    def __init__(self, ctx: AppContext, project: GeneratedProject, job: _Job) -> None:
        self.ctx = ctx
        self.id, self.owner = project.id, project.owner
        self.job = job
        self.progress: dict[str, Any] = dict(project.progress)
        self.log: list[dict[str, Any]] = []
        self.usage = Usage()
        self._written = 0.0

    def _write(self, **changes: Any) -> GeneratedProject:
        try:
            current = self.ctx.generated_source.get(self.owner, self.id)
        except KeyError as exc:
            raise Cancelled from exc
        if current.status is not GenerationStatus.GENERATING:
            raise Cancelled
        current.progress = dict(self.progress)
        current.log = list(self.log)
        current.usage = self.usage.to_json()
        for name, value in changes.items():
            setattr(current, name, value)
        self._written = time.monotonic()
        return self.ctx.generated_source.update(current)

    def on_progress(self, phase: str, attempt: int, detail: str) -> None:
        if self.job.cancel.is_set():
            raise Cancelled
        moved = (phase, attempt) != (self.progress.get("phase"), self.progress.get("attempt"))
        self.progress = {"phase": phase, "attempt": attempt, "detail": detail}
        self.job.version += 1
        if moved or time.monotonic() - self._written >= _WRITE_EVERY_S:
            self._write()

    def on_log(self, attempt: int, kind: str, message: str) -> None:
        self.log.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "attempt": attempt,
                "kind": kind,
                "message": message,
            }
        )
        self.job.version += 1
        self._write()

    def finish(self, status: GenerationStatus, **changes: Any) -> None:
        with contextlib.suppress(Cancelled):
            self._write(status=status, finished_at=datetime.now(UTC), **changes)


def _work(
    ctx: AppContext, project: GeneratedProject, request: GenerationRequest, job: _Job
) -> None:
    reporter = _Reporter(ctx, project, job)
    try:
        sandbox = sandbox_client(ctx)
        stack = STACKS[request.stack]
        scaffold = builtin_templates()[stack.template].files
        pack = next(p for p in sandbox.packs() if p["name"] == stack.pack)
        allowed = dict((pack.get("dependencies") or {}).get("allowed") or {})
        hooks = Hooks(
            progress=reporter.on_progress,
            log=reporter.on_log,
            cancelled=job.cancel.is_set,
            preview_base=new_preview_base,
        )
        result = generate(
            ctx.anthropic_client,
            generator_model(),
            sandbox,
            request,
            scaffold,
            allowed,
            hooks,
            reporter.usage,
        )
        reporter.progress = {"phase": "ready", "attempt": result.attempts - 1, "detail": "Ready"}
        reporter.finish(
            GenerationStatus.READY,
            artifact=result.artifact.to_json(),
            title=result.artifact.title,
        )
        if project.parent_id:
            # Replaced; kept if a session started from it meanwhile.
            with contextlib.suppress(HTTPException):
                delete_project(ctx, project.owner, project.parent_id)
    except Cancelled:
        reporter.finish(GenerationStatus.CANCELLED, error="Cancelled")
    except GenerationFailed as exc:
        reporter.finish(GenerationStatus.FAILED, error=str(exc))
    except anthropic.APIError as exc:
        reporter.finish(GenerationStatus.FAILED, error=f"The model could not be reached: {exc}")
    except (SandboxUnavailable, SandboxRequestError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, (SandboxRequestError, HTTPException)) else exc
        reporter.finish(GenerationStatus.FAILED, error=f"The sandbox runner failed: {detail}")
    except Exception as exc:  # A thread must leave the row finished, whatever happened.
        log.exception("Generating project %s failed", project.id)
        reporter.log.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "attempt": reporter.progress.get("attempt", 0),
                "kind": "crash",
                "message": "".join(traceback.format_exception(exc))[-4000:],
            }
        )
        reporter.finish(GenerationStatus.FAILED, error=f"Unexpected error: {exc}")
    finally:
        job.done = True
        job.version += 1
        _jobs.pop(project.id, None)


# --------------------------------------------------------------------------- #
# Previewing and starting a round
# --------------------------------------------------------------------------- #


def preview_sandbox_id(project_id: str) -> str:
    return f"gen-{project_id}"


def _ready(ctx: AppContext, owner: str, project_id: str) -> tuple[GeneratedProject, Artifact]:
    project = _get(ctx, owner, project_id)
    if project.status is not GenerationStatus.READY or project.artifact is None:
        raise HTTPException(status_code=409, detail="This project is not ready")
    return project, Artifact.from_json(project.artifact)


def _destroy_preview(ctx: AppContext, project_id: str) -> None:
    if ctx.sandbox is not None:
        with contextlib.suppress(SandboxUnavailable, SandboxRequestError):
            ctx.sandbox.destroy(preview_sandbox_id(project_id))


def preview_status(ctx: AppContext, owner: str, project_id: str) -> dict[str, Any]:
    """``{state: none|running|stopped, base, servers}`` of the project's
    preview sandbox."""
    _ready(ctx, owner, project_id)
    sandbox = sandbox_client(ctx)
    sid = preview_sandbox_id(project_id)
    try:
        with runner_errors():
            info = sandbox.info(sid)
            running = info["state"] == "running"
            servers = sandbox.servers(sid) if running else []
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"state": "none", "base": None, "servers": []}
        raise
    return {"state": info["state"], "base": info.get("previewBase"), "servers": servers}


def start_preview(ctx: AppContext, owner: str, project_id: str) -> dict[str, Any]:
    """Start (or resume) the preview sandbox from the validated baseline."""
    _, artifact = _ready(ctx, owner, project_id)
    sandbox = sandbox_client(ctx)
    sid = preview_sandbox_id(project_id)
    status = preview_status(ctx, owner, project_id)
    with runner_errors():
        if status["state"] == "none":
            sandbox.create(sid, STACKS[artifact.stack].pack, artifact.files, new_preview_base(sid))
        elif status["state"] != "running":
            sandbox.resume(sid)
    return preview_status(ctx, owner, project_id)


def stop_preview(ctx: AppContext, owner: str, project_id: str) -> None:
    _get(ctx, owner, project_id)
    _destroy_preview(ctx, project_id)


def server_action(
    ctx: AppContext, owner: str, project_id: str, name: str, action: str
) -> dict[str, Any]:
    _ready(ctx, owner, project_id)
    if action not in SERVER_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown server action {action!r}")
    with runner_errors():
        sandbox_client(ctx).server_action(preview_sandbox_id(project_id), name, action)
    return preview_status(ctx, owner, project_id)


def server_logs(
    ctx: AppContext, owner: str, project_id: str, name: str, since: int
) -> dict[str, Any]:
    _ready(ctx, owner, project_id)
    with runner_errors():
        return sandbox_client(ctx).server_logs(preview_sandbox_id(project_id), name, max(0, since))


def start_round(
    ctx: AppContext,
    owner: str,
    project_id: str,
    question_id: str | None,
    rubric_id: str | None,
    guideline_id: str | None,
) -> str:
    """Start a staged, AI-assisted live round in the project; returns the
    session id. The preview sandbox goes first (the runner caps how many
    run at once)."""
    _ready(ctx, owner, project_id)
    _destroy_preview(ctx, project_id)
    return mock_staged.start_round(ctx, project_id, question_id, rubric_id, guideline_id)
