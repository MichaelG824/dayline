"""HTTP controller for mock interviews: question bank, ingest, rubrics,
guidelines, sessions, and grading."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dayline.api.context import ContextDep
from dayline.api.services import mock as service

router = APIRouter()

# camelCase request fields -> snake_case service fields.
_QUESTION_FIELDS = {
    "source": "source",
    "sourceUrl": "source_url",
    "company": "company",
    "role": "role",
    "roundType": "round_type",
    "title": "title",
    "promptMd": "prompt_md",
    "constraints": "constraints",
    "followUps": "follow_ups",
    "languageHint": "language_hint",
    "originalText": "original_text",
    "originalLanguage": "original_language",
    "reportedOn": "reported_on",
    "canonicalId": "canonical_id",
    "notes": "notes",
}


class QuestionFieldsRequest(BaseModel):
    """Every field is optional so PATCH can send just what changed; an
    explicit ``null`` clears a nullable field."""

    source: str | None = None
    sourceUrl: str | None = None
    company: str | None = None
    role: str | None = None
    roundType: str | None = None
    title: str | None = None
    promptMd: str | None = None
    constraints: list[str] | None = None
    followUps: list[str] | None = None
    languageHint: str | None = None
    originalText: str | None = None
    originalLanguage: str | None = None
    reportedOn: str | None = None
    canonicalId: str | None = None
    notes: str | None = None

    def changes(self) -> dict[str, Any]:
        """The fields the client actually sent, snake_cased for the service."""
        return {_QUESTION_FIELDS[k]: v for k, v in self.model_dump(exclude_unset=True).items()}


@router.get("/api/mock/questions")
def list_questions(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_questions(ctx)


@router.get("/api/mock/questions/{question_id}")
def get_question(question_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.get_question(ctx, question_id)


@router.post("/api/mock/questions", status_code=201)
def create_question(body: QuestionFieldsRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_question(ctx, body.changes())


@router.patch("/api/mock/questions/{question_id}")
def update_question(
    question_id: str, body: QuestionFieldsRequest, ctx: ContextDep
) -> dict[str, Any]:
    return service.update_question(ctx, question_id, body.changes())


@router.delete("/api/mock/questions/{question_id}", status_code=204)
def delete_question(question_id: str, ctx: ContextDep) -> None:
    service.delete_question(ctx, question_id)


class ExtractRequest(BaseModel):
    text: str


@router.post("/api/mock/extract")
def extract(body: ExtractRequest, ctx: ContextDep) -> dict[str, Any]:
    """Extract questions from a pasted post. Saves nothing."""
    return service.extract_from_post(ctx, body.text)


class RubricRequest(BaseModel):
    name: str
    roundType: str | None = None
    criteria: list[dict[str, Any]]


@router.get("/api/mock/rubrics")
def list_rubrics(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_rubrics(ctx)


@router.post("/api/mock/rubrics", status_code=201)
def create_rubric(body: RubricRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_rubric(ctx, body.name, body.roundType, body.criteria)


@router.put("/api/mock/rubrics/{rubric_id}")
def update_rubric(rubric_id: str, body: RubricRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.update_rubric(ctx, rubric_id, body.name, body.roundType, body.criteria)


@router.delete("/api/mock/rubrics/{rubric_id}", status_code=204)
def delete_rubric(rubric_id: str, ctx: ContextDep) -> None:
    service.delete_rubric(ctx, rubric_id)


class GuidelineRequest(BaseModel):
    name: str
    bodyMd: str = ""


@router.get("/api/mock/guidelines")
def list_guidelines(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_guidelines(ctx)


@router.post("/api/mock/guidelines", status_code=201)
def create_guideline(body: GuidelineRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_guideline(ctx, body.name, body.bodyMd)


@router.put("/api/mock/guidelines/{guideline_id}")
def update_guideline(guideline_id: str, body: GuidelineRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.update_guideline(ctx, guideline_id, body.name, body.bodyMd)


@router.delete("/api/mock/guidelines/{guideline_id}", status_code=204)
def delete_guideline(guideline_id: str, ctx: ContextDep) -> None:
    service.delete_guideline(ctx, guideline_id)


class SessionRequest(BaseModel):
    title: str = ""
    transcript: str
    questionId: str | None = None
    rubricId: str | None = None
    guidelineId: str | None = None


@router.get("/api/mock/sessions")
def list_sessions(ctx: ContextDep) -> list[dict[str, Any]]:
    return service.list_sessions(ctx)


@router.get("/api/mock/sessions/{session_id}")
def get_session(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    return service.get_session(ctx, session_id)


@router.post("/api/mock/sessions", status_code=201)
def create_session(body: SessionRequest, ctx: ContextDep) -> dict[str, Any]:
    return service.create_session(
        ctx, body.title, body.transcript, body.questionId, body.rubricId, body.guidelineId
    )


@router.post("/api/mock/sessions/{session_id}/grade")
def grade_session(session_id: str, ctx: ContextDep) -> dict[str, Any]:
    """Grade (or re-grade) a session. Slow: one strong-model call."""
    return service.grade_session(ctx, session_id)


@router.delete("/api/mock/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, ctx: ContextDep) -> None:
    service.delete_session(ctx, session_id)
