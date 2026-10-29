"""HTTP controller for LeetCode problems, their solutions, and tags."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import problems as service

router = APIRouter()


class ProblemFieldsRequest(BaseModel):
    """Every field is optional so PATCH can send just what changed; an
    explicit ``null`` clears a nullable field (e.g. ``number``)."""

    title: str | None = None
    difficulty: str | None = None
    status: str | None = None
    number: int | None = None
    slug: str | None = None
    url: str | None = None
    confidence: int | None = None
    notes: str | None = None
    starred: bool | None = None
    tagIds: list[str] | None = None

    def changes(self) -> dict[str, Any]:
        """The fields the client actually sent, snake_cased for the service."""
        sent = self.model_dump(exclude_unset=True)
        if "tagIds" in sent:
            sent["tag_ids"] = sent.pop("tagIds") or []
        return sent


@router.get("/api/problems")
def list_problems(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_problems(ctx)


@router.get("/api/problems/export")
def export_problems(ctx: ContextDep) -> dict[str, Any]:
    return service.export_problems(ctx)


@router.get("/api/problems/{problem_id}")
def get_problem(problem_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.get_problem(ctx, problem_id)


@router.post("/api/problems", status_code=201)
def create_problem(body: ProblemFieldsRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_problem(ctx, body.changes())


@router.patch("/api/problems/{problem_id}")
def update_problem(problem_id: str, body: ProblemFieldsRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.update_problem(ctx, problem_id, body.changes())


@router.delete("/api/problems/{problem_id}", status_code=204)
def delete_problem(problem_id: str, ctx: ContextDep) -> None:
    service.delete_problem(ctx, problem_id)


class SolutionRequest(BaseModel):
    title: str
    language: str
    code: str = ""
    timeComplexity: str | None = None
    spaceComplexity: str | None = None
    explanation: str = ""
    isOptimal: bool = False


@router.post("/api/problems/{problem_id}/solutions", status_code=201)
def create_solution(problem_id: str, body: SolutionRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_solution(
        ctx,
        problem_id,
        title=body.title,
        language=body.language,
        code=body.code,
        time_complexity=body.timeComplexity,
        space_complexity=body.spaceComplexity,
        explanation=body.explanation,
        is_optimal=body.isOptimal,
    )


@router.put("/api/solutions/{solution_id}")
def update_solution(solution_id: str, body: SolutionRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.update_solution(
        ctx,
        solution_id,
        title=body.title,
        language=body.language,
        code=body.code,
        time_complexity=body.timeComplexity,
        space_complexity=body.spaceComplexity,
        explanation=body.explanation,
        is_optimal=body.isOptimal,
    )


@router.delete("/api/solutions/{solution_id}", status_code=204)
def delete_solution(solution_id: str, ctx: ContextDep) -> None:
    service.delete_solution(ctx, solution_id)


class TagRequest(BaseModel):
    name: str
    color: str | None = None


@router.get("/api/problem-tags")
def list_tags(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_tags(ctx)


@router.post("/api/problem-tags", status_code=201)
def create_tag(body: TagRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_tag(ctx, name=body.name, color=body.color)


@router.put("/api/problem-tags/{tag_id}")
def update_tag(tag_id: str, body: TagRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.update_tag(ctx, tag_id, name=body.name, color=body.color)


@router.delete("/api/problem-tags/{tag_id}", status_code=204)
def delete_tag(tag_id: str, ctx: ContextDep) -> None:
    service.delete_tag(ctx, tag_id)
