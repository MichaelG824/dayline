"""Mock-interview orchestration (the Mock tab): question bank + ingest,
rubrics, guidelines, sessions, and grading.

The LLM work lives in ``dayline.mock`` (no FastAPI there); this module validates
requests, wires those functions to the mock source, and turns their errors
into HTTP errors. Grading never creates tasks: a scorecard's weak areas come
back as ``propose_new_task`` proposals for the existing chat confirm path.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

import anthropic
from fastapi import HTTPException

from dayline.adapters.sandbox import SandboxRequestError, SandboxUnavailable
from dayline.api.context import AppContext
from dayline.api.parsing import parse_mock_question_source, parse_mock_round_type
from dayline.api.serializers import (
    mock_event_json,
    mock_guideline_json,
    mock_question_json,
    mock_rubric_json,
    mock_session_json,
    replay_json,
    scorecard_json,
    staged_round_json,
    task_json,
)
from dayline.api.services.staged_clock import catch_up
from dayline.api.services.staged_problems import session_problem
from dayline.mock import grader_model, mock_model, round_metrics, staged
from dayline.mock.grader import GradeInput, GradingError, grade, weak_area_proposals
from dayline.mock.ingest import ExtractionError, extract_questions, find_similar
from dayline.mock.templates import builtin_templates
from dayline.mock.worklog import replay, work_record
from dayline.models import (
    MockGuideline,
    MockQuestion,
    MockRoundType,
    MockRubric,
    MockSession,
    MockSessionKind,
    MockSessionStatus,
    RubricCriterion,
)

EDITABLE_QUESTION_FIELDS = frozenset(
    {
        "source",
        "source_url",
        "company",
        "role",
        "round_type",
        "title",
        "prompt_md",
        "constraints",
        "follow_ups",
        "language_hint",
        "original_text",
        "original_language",
        "reported_on",
        "canonical_id",
        "notes",
    }
)

MAX_CRITERIA = 12
MAX_WEIGHT = 10.0


def _not_found(kind: str, item_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No {kind} {item_id!r}")


def _llm_error(exc: anthropic.APIError) -> HTTPException:
    return HTTPException(status_code=502, detail=f"The model call failed: {exc.message}")


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _clean_list(value: Any) -> list[str]:
    return [str(s).strip() for s in value or [] if str(s).strip()]


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #


def _get_question(ctx: AppContext, question_id: str) -> MockQuestion:
    try:
        return ctx.mock_source.get_question(question_id)
    except KeyError as exc:
        raise _not_found("question", question_id) from exc


def _canonical_target(ctx: AppContext, question_id: str, canonical_id: str | None) -> str | None:
    """Resolve "same as X" to X's own canonical question, so copies always
    point at a root (one level deep) and never at themselves."""
    if canonical_id is None:
        return None
    target = _get_question(ctx, canonical_id)
    root = target.canonical_id or target.id
    if root == question_id:
        raise HTTPException(status_code=400, detail="A question cannot be a copy of itself")
    return root


def _apply_question_changes(
    ctx: AppContext, question: MockQuestion, changes: dict[str, Any]
) -> None:
    unknown = set(changes) - EDITABLE_QUESTION_FIELDS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown fields {sorted(unknown)!r}")
    for key, value in changes.items():
        if key == "title":
            title = (value or "").strip()
            if not title:
                raise HTTPException(status_code=400, detail="Title is required")
            question.title = title
        elif key == "round_type":
            question.round_type = parse_mock_round_type(value)
        elif key == "source":
            question.source = parse_mock_question_source(value)
        elif key in ("constraints", "follow_ups"):
            setattr(question, key, _clean_list(value))
        elif key == "reported_on":
            try:
                question.reported_on = date.fromisoformat(value) if value else None
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="reportedOn must be YYYY-MM-DD"
                ) from exc
        elif key == "canonical_id":
            question.canonical_id = _canonical_target(ctx, question.id, _blank_to_none(value))
        elif key in ("prompt_md", "original_text", "notes"):
            setattr(question, key, value or "")
        else:  # source_url, company, role, language_hint, original_language
            setattr(question, key, _blank_to_none(value))


def list_questions(ctx: AppContext) -> list[dict[str, Any]]:
    """Canonical questions only, each with how many times it was reported."""
    questions = ctx.mock_source.list_questions()
    copies: dict[str, int] = {}
    for q in questions:
        if q.canonical_id:
            copies[q.canonical_id] = copies.get(q.canonical_id, 0) + 1
    return [
        mock_question_json(q, times_seen=1 + copies.get(q.id, 0))
        for q in questions
        if q.canonical_id is None
    ]


def get_question(ctx: AppContext, question_id: str) -> dict[str, Any]:
    """One question with its reported copies and the sessions that used it."""
    question = _get_question(ctx, question_id)
    copies = [q for q in ctx.mock_source.list_questions() if q.canonical_id == question.id]
    cards = ctx.mock_source.latest_scorecards()
    sessions = [
        mock_session_json(s, cards.get(s.id))
        for s in ctx.mock_source.list_sessions()
        if s.question_id == question.id
    ]
    return {
        **mock_question_json(question, times_seen=1 + len(copies)),
        "copies": [mock_question_json(q) for q in copies],
        "sessions": sessions,
    }


def create_question(ctx: AppContext, changes: dict[str, Any]) -> dict[str, Any]:
    if not changes.get("title") or not changes.get("round_type"):
        raise HTTPException(status_code=400, detail="Title and round type are required")
    question = MockQuestion(
        id=str(uuid.uuid4()),
        title=changes["title"],
        round_type=parse_mock_round_type(changes["round_type"]),
    )
    _apply_question_changes(ctx, question, changes)
    return mock_question_json(ctx.mock_source.create_question(question))


def update_question(ctx: AppContext, question_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    question = _get_question(ctx, question_id)
    _apply_question_changes(ctx, question, changes)
    return mock_question_json(ctx.mock_source.update_question(question))


def delete_question(ctx: AppContext, question_id: str) -> None:
    ctx.mock_source.delete_question(question_id)


def extract_from_post(ctx: AppContext, post: str) -> dict[str, Any]:
    """Extract questions from a pasted post and suggest likely duplicates.
    Saves nothing - the client posts each reviewed question back."""
    try:
        extraction = extract_questions(ctx.anthropic_client, mock_model(), post)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except anthropic.APIError as exc:
        raise _llm_error(exc) from exc

    bank = ctx.mock_source.list_questions()
    return {
        "originalLanguage": extraction.original_language,
        "questions": [
            {
                "title": q.title,
                "roundType": q.round_type.value,
                "promptMd": q.prompt_md,
                "company": q.company,
                "role": q.role,
                "constraints": q.constraints,
                "followUps": q.follow_ups,
                "languageHint": q.language_hint,
                "reportedOn": q.reported_on.isoformat() if q.reported_on else None,
                "similar": [
                    {"id": match.id, "title": match.title, "company": match.company, "score": score}
                    for match, score in find_similar(q.title, q.prompt_md, bank)
                ],
            }
            for q in extraction.questions
        ],
    }


# --------------------------------------------------------------------------- #
# Rubrics + guidelines
# --------------------------------------------------------------------------- #

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG.sub("_", text.lower()).strip("_")


def _parse_criteria(raw: list[dict[str, Any]]) -> list[RubricCriterion]:
    if not raw:
        raise HTTPException(status_code=400, detail="A rubric needs at least one criterion")
    if len(raw) > MAX_CRITERIA:
        raise HTTPException(status_code=400, detail=f"At most {MAX_CRITERIA} criteria")
    criteria: list[RubricCriterion] = []
    for item in raw:
        title = str(item.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Every criterion needs a title")
        # Keys are the grader's stable ids; derive one from the title when the
        # client doesn't send it, and keep it once set so old cards still match.
        key = _slug(str(item.get("key") or "")) or _slug(title)
        try:
            weight = float(item.get("weight", 1))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Bad weight for {title!r}") from exc
        if not 0 < weight <= MAX_WEIGHT:
            raise HTTPException(status_code=400, detail=f"Weight for {title!r} must be 0-10")
        criteria.append(
            RubricCriterion(
                key=key,
                title=title,
                description=str(item.get("description") or "").strip(),
                weight=weight,
            )
        )
    keys = [c.key for c in criteria]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise HTTPException(status_code=400, detail=f"Duplicate criterion keys {duplicates!r}")
    return criteria


def _rubric_fields(name: str, round_type: str | None) -> tuple[str, MockRoundType | None]:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Name is required")
    return clean, parse_mock_round_type(round_type) if round_type else None


def list_rubrics(ctx: AppContext) -> list[dict[str, Any]]:
    return [mock_rubric_json(r) for r in ctx.mock_source.list_rubrics()]


def create_rubric(
    ctx: AppContext, name: str, round_type: str | None, criteria: list[dict[str, Any]]
) -> dict[str, Any]:
    clean_name, parsed_round = _rubric_fields(name, round_type)
    rubric = MockRubric(
        id=str(uuid.uuid4()),
        name=clean_name,
        round_type=parsed_round,
        criteria=_parse_criteria(criteria),
    )
    return mock_rubric_json(ctx.mock_source.create_rubric(rubric))


def update_rubric(
    ctx: AppContext,
    rubric_id: str,
    name: str,
    round_type: str | None,
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        rubric = ctx.mock_source.get_rubric(rubric_id)
    except KeyError as exc:
        raise _not_found("rubric", rubric_id) from exc
    rubric.name, rubric.round_type = _rubric_fields(name, round_type)
    rubric.criteria = _parse_criteria(criteria)
    return mock_rubric_json(ctx.mock_source.update_rubric(rubric))


def delete_rubric(ctx: AppContext, rubric_id: str) -> None:
    ctx.mock_source.delete_rubric(rubric_id)


def list_guidelines(ctx: AppContext) -> list[dict[str, Any]]:
    return [mock_guideline_json(g) for g in ctx.mock_source.list_guidelines()]


def create_guideline(ctx: AppContext, name: str, body_md: str) -> dict[str, Any]:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    guideline = MockGuideline(id=str(uuid.uuid4()), name=name.strip(), body_md=body_md)
    return mock_guideline_json(ctx.mock_source.create_guideline(guideline))


def update_guideline(ctx: AppContext, guideline_id: str, name: str, body_md: str) -> dict[str, Any]:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        guideline = ctx.mock_source.get_guideline(guideline_id)
    except KeyError as exc:
        raise _not_found("guideline", guideline_id) from exc
    guideline.name, guideline.body_md = name.strip(), body_md
    return mock_guideline_json(ctx.mock_source.update_guideline(guideline))


def delete_guideline(ctx: AppContext, guideline_id: str) -> None:
    ctx.mock_source.delete_guideline(guideline_id)


# --------------------------------------------------------------------------- #
# Sessions + grading
# --------------------------------------------------------------------------- #


def _get_session(ctx: AppContext, session_id: str) -> MockSession:
    try:
        return ctx.mock_source.get_session(session_id)
    except KeyError as exc:
        raise _not_found("session", session_id) from exc


def round_type_of(ctx: AppContext, session: MockSession) -> MockRoundType | None:
    """The round type of a live session's template or staged problem."""
    problem = session_problem(ctx, session)
    if problem is not None:
        return problem.round_type
    template = builtin_templates().get(session.template_id or "")
    return template.round_type if template else None


def assistant_enabled(ctx: AppContext, session: MockSession) -> bool:
    """Whether the session's workspace has the AI assistant: live
    AI-assisted rounds only (``services/mock_assistant.py``)."""
    return (
        session.kind is MockSessionKind.LIVE
        and round_type_of(ctx, session) is MockRoundType.AI_ASSISTED_PROJECT
    )


def analysed_round(ctx: AppContext, session: MockSession) -> bool:
    """Whether grading analyses the round (metrics, key points citing
    moments): staged AI-assisted rounds, which generated projects are."""
    return session.staged_problem_id is not None and assistant_enabled(ctx, session)


def list_sessions(ctx: AppContext) -> list[dict[str, Any]]:
    cards = ctx.mock_source.latest_scorecards()
    return [mock_session_json(s, cards.get(s.id)) for s in ctx.mock_source.list_sessions()]


def get_session(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """The full record: transcript, latest scorecard, its weak areas as
    proposals, and the prep tasks already created from them. A live session
    also carries its task, events, last test run, and final diff (its
    sandbox's state comes from ``GET /api/mock/sessions/{id}/sandbox``)."""
    session = _get_session(ctx, session_id)
    card = ctx.mock_source.latest_scorecards().get(session_id)
    linked = [t for t in ctx.task_source.list_tasks() if t.mock_session_id == session_id]
    detail = {
        **mock_session_json(session, card),
        "transcript": session.transcript,
        "scorecard": scorecard_json(card) if card else None,
        "proposals": weak_area_proposals(card) if card else [],
        "tasks": [task_json(t, ctx.task_source) for t in linked],
    }
    if session.kind is MockSessionKind.LIVE:
        template = builtin_templates().get(session.template_id or "")
        problem = session_problem(ctx, session)
        if problem is not None:
            catch_up(ctx, session, problem)
        events = ctx.mock_source.list_events(session_id)
        detail |= {
            "templateTitle": template.title if template else None,
            "taskMd": template.task_md if template else "",
            "durationMin": template.duration_min if template else None,
            "openPath": template.open_path if template else None,
            "testReport": session.test_report,
            "finalDiff": session.final_diff,
            "events": [mock_event_json(e) for e in events],
            "staged": None,
            "assistant": assistant_enabled(ctx, session),
        }
        if problem is not None:
            detail |= {
                "templateTitle": problem.title,
                "taskMd": problem.overview_md,
                "durationMin": problem.duration_min,
                "openPath": problem.open_path,
                "staged": staged_round_json(problem, session, events, datetime.now(UTC)),
            }
    return detail


def get_replay(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Everything that happened in a live session, in order, for the replay."""
    session = _get_session(ctx, session_id)
    if session.kind is not MockSessionKind.LIVE:
        raise HTTPException(status_code=404, detail="Only live sessions have a replay")
    problem = session_problem(ctx, session)
    if problem is not None:
        catch_up(ctx, session, problem)
    events = ctx.mock_source.list_events(session_id)
    now = datetime.now(UTC)
    data = replay_json(session, replay(events, session.started_at), now)
    # An AI-assisted round also shows the numbers its analysis is given.
    data["metrics"] = []
    if session.started_at is not None and analysed_round(ctx, session):
        metrics = round_metrics.compute(
            problem, session.stages, events, session.started_at, session.ended_at or now
        )
        lines = round_metrics.metrics_text(metrics).splitlines()[1:]
        data["metrics"] = [line.removeprefix("- ") for line in lines]
    return data


def check_session_refs(
    ctx: AppContext, question_id: str | None, rubric_id: str | None, guideline_id: str | None
) -> None:
    """404 when a referenced question, rubric, or guideline does not exist."""
    lookups = (
        ("question", question_id, ctx.mock_source.get_question),
        ("rubric", rubric_id, ctx.mock_source.get_rubric),
        ("guideline", guideline_id, ctx.mock_source.get_guideline),
    )
    for kind, item_id, getter in lookups:
        if item_id:
            try:
                getter(item_id)
            except KeyError as exc:
                raise _not_found(kind, item_id) from exc


def create_session(
    ctx: AppContext,
    title: str,
    transcript: str,
    question_id: str | None,
    rubric_id: str | None,
    guideline_id: str | None,
) -> dict[str, Any]:
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Paste a transcript first")
    check_session_refs(ctx, question_id, rubric_id, guideline_id)
    session = MockSession(
        id=str(uuid.uuid4()),
        title=title.strip() or "Pasted transcript",
        question_id=question_id or None,
        rubric_id=rubric_id or None,
        guideline_id=guideline_id or None,
        transcript=transcript,
    )
    created = ctx.mock_source.create_session(session)
    return get_session(ctx, created.id)


def grade_session(ctx: AppContext, session_id: str) -> dict[str, Any]:
    """Grade (or re-grade) a session; each run stores a new scorecard."""
    session = _get_session(ctx, session_id)
    if session.status is MockSessionStatus.LIVE:
        raise HTTPException(status_code=409, detail="End the session before grading it")
    if not session.rubric_id:
        raise HTTPException(status_code=400, detail="Pick a rubric before grading")
    try:
        rubric = ctx.mock_source.get_rubric(session.rubric_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="This session's rubric was deleted") from exc
    guideline = None
    if session.guideline_id:
        try:
            guideline = ctx.mock_source.get_guideline(session.guideline_id)
        except KeyError:
            guideline = None  # Deleted since; grade on the rubric alone.
    question = None
    if session.question_id:
        try:
            question = ctx.mock_source.get_question(session.question_id)
        except KeyError:
            question = None

    events = ctx.mock_source.list_events(session_id)
    work = work_record(session, events)
    problem = session_problem(ctx, session)
    now = session.ended_at or datetime.now(UTC)
    # A staged AI-assisted round (a generated one) is analysed: metrics
    # computed here, key points that cite moments.
    analysed = analysed_round(ctx, session)
    if analysed and session.started_at is not None:
        metrics = round_metrics.compute(problem, session.stages, events, session.started_at, now)
        work = f"{round_metrics.metrics_text(metrics)}\n\n{work}"
    if problem is not None:
        work = f"{staged.round_record(problem, session.stages, now)}\n\n{work}"
    data = GradeInput(
        transcript=session.transcript,
        rubric=rubric,
        guideline=guideline,
        question=question,
        work=work,
        hints=problem.analysis_hints if problem else (),
        key_points=analysed,
    )
    try:
        card = grade(ctx.anthropic_client, grader_model(), data, session.id)
    except GradingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except anthropic.APIError as exc:
        raise _llm_error(exc) from exc
    ctx.mock_source.create_scorecard(card)
    return get_session(ctx, session_id)


def delete_session(ctx: AppContext, session_id: str) -> None:
    try:
        session = ctx.mock_source.get_session(session_id)
    except KeyError:
        return
    if session.kind is MockSessionKind.LIVE and ctx.sandbox is not None:
        # Best effort: the runner's reaper deletes anything left behind.
        with contextlib.suppress(SandboxUnavailable, SandboxRequestError):
            ctx.sandbox.destroy(session_id)
    ctx.mock_source.delete_session(session_id)
