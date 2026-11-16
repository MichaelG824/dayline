"""Generated practice projects: generate, follow progress, cancel,
regenerate, delete, preview, and start a round. Logic lives in
``services/mock_generate.py``.

Projects are private to the signed-in account: every route reads the
owner from the session the auth gate verified.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from dayline.api.context import ContextDep
from dayline.api.services import mock as mock_service
from dayline.api.services import mock_generate as service
from dayline.models import InterviewerStyle

router = APIRouter()
BASE = "/api/mock/generated"


def current_owner(request: Request) -> str:
    """The signed-in email (``api/auth.py``'s gate sets it on every /api call)."""
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    return str(identity.email).strip().lower()


OwnerDep = Annotated[str, Depends(current_owner)]


class ContextFileBody(BaseModel):
    name: str
    content: str


class CreateRequest(BaseModel):
    prompt: str
    stack: str
    difficulty: str
    durationMin: int  # noqa: N815 - wire format is camelCase
    changeRequestMin: int  # noqa: N815
    contextFiles: list[ContextFileBody] = Field(default_factory=list)  # noqa: N815


class RegenerateRequest(BaseModel):
    feedback: str = ""


class StartRequest(BaseModel):
    questionId: str | None = None  # noqa: N815
    rubricId: str | None = None  # noqa: N815
    guidelineId: str | None = None  # noqa: N815
    # Realistic unless the candidate picks the coach.
    interviewerStyle: InterviewerStyle = InterviewerStyle.REALISTIC  # noqa: N815


@router.get(BASE)
def list_projects(ctx: ContextDep, owner: OwnerDep) -> list[dict[str, Any]]:
    return service.list_projects(ctx, owner)


@router.post(BASE, status_code=201)
def create_project(body: CreateRequest, ctx: ContextDep, owner: OwnerDep) -> dict[str, Any]:
    """Start generating (2-5 minutes, in the background); follow it with GET."""
    return service.create_project(
        ctx,
        owner,
        prompt=body.prompt,
        stack=body.stack,
        difficulty=body.difficulty,
        duration_min=body.durationMin,
        change_request_min=body.changeRequestMin,
        context_files=[(f.name, f.content) for f in body.contextFiles],
    )


@router.get(BASE + "/{project_id}")
async def get_project(
    project_id: str,
    ctx: ContextDep,
    owner: OwnerDep,
    version: int | None = None,
    wait: float = 0,
) -> dict[str, Any]:
    """The project. With ``version`` and ``wait`` (seconds, at most 25) it
    is a long poll: it answers once the progress moves past ``version``."""
    return await service.wait_project(ctx, owner, project_id, version, wait)


@router.post(BASE + "/{project_id}/cancel")
def cancel(project_id: str, ctx: ContextDep, owner: OwnerDep) -> dict[str, Any]:
    return service.cancel(ctx, owner, project_id)


@router.post(BASE + "/{project_id}/regenerate", status_code=201)
def regenerate(
    project_id: str, body: RegenerateRequest, ctx: ContextDep, owner: OwnerDep
) -> dict[str, Any]:
    return service.regenerate(ctx, owner, project_id, body.feedback)


@router.delete(BASE + "/{project_id}", status_code=204)
def delete_project(project_id: str, ctx: ContextDep, owner: OwnerDep) -> None:
    service.delete_project(ctx, owner, project_id)


@router.get(BASE + "/{project_id}/preview")
def preview_status(project_id: str, ctx: ContextDep, owner: OwnerDep) -> dict[str, Any]:
    return service.preview_status(ctx, owner, project_id)


@router.post(BASE + "/{project_id}/preview")
def start_preview(project_id: str, ctx: ContextDep, owner: OwnerDep) -> dict[str, Any]:
    """Start the app from the baseline in a sandbox of its own."""
    return service.start_preview(ctx, owner, project_id)


@router.delete(BASE + "/{project_id}/preview", status_code=204)
def stop_preview(project_id: str, ctx: ContextDep, owner: OwnerDep) -> None:
    service.stop_preview(ctx, owner, project_id)


@router.post(BASE + "/{project_id}/servers/{name}/{action}")
def server_action(
    project_id: str, name: str, action: str, ctx: ContextDep, owner: OwnerDep
) -> dict[str, Any]:
    return service.server_action(ctx, owner, project_id, name, action)


@router.get(BASE + "/{project_id}/servers/{name}/logs")
def server_logs(
    project_id: str, name: str, ctx: ContextDep, owner: OwnerDep, since: int = 0
) -> dict[str, Any]:
    return service.server_logs(ctx, owner, project_id, name, since)


@router.post(BASE + "/{project_id}/start", status_code=201)
def start_round(
    project_id: str, body: StartRequest, ctx: ContextDep, owner: OwnerDep
) -> dict[str, Any]:
    """Start an AI-assisted staged round in the project; returns the session."""
    session_id = service.start_round(
        ctx,
        owner,
        project_id,
        body.questionId,
        body.rubricId,
        body.guidelineId,
        body.interviewerStyle,
    )
    return mock_service.get_session(ctx, session_id)
