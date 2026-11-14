"""Domain-object -> JSON serializers for the API responses.

These produce the exact dict shapes the Next.js client consumes (see
``web/app/lib/api.ts``); the services return them straight through, so keeping
them isolated here keeps the JSON contract in one place.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

from dayline.adapters.application_source import SupabaseApplicationSource
from dayline.adapters.task_source import SupabaseTaskSource
from dayline.models import (
    Application,
    Interview,
    MockEvent,
    MockGuideline,
    MockQuestion,
    MockRubric,
    MockSession,
    Plan,
    Problem,
    ProblemTag,
    Scorecard,
    Solution,
    Task,
)


def task_json(task: Task, task_source: SupabaseTaskSource) -> dict[str, Any]:
    scheduled = task_source.scheduled_time_of(task.id)
    return {
        "id": task.id,
        "name": task.name,
        "category": task.category.value,
        "priority": task.priority.name,
        "status": task.status.value,
        "estDurationMin": task.est_duration_min,
        "scheduledTime": scheduled.isoformat() if scheduled else None,
        "plannedDate": task.planned_date.isoformat() if task.planned_date else None,
        "fixedTime": task.fixed_time.isoformat() if task.fixed_time else None,
        "preferredWindow": task.preferred_window.value if task.preferred_window else None,
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "recurs": task.recurs.value if task.recurs else None,
        "recurDay": task.recur_day.value if task.recur_day else None,
        "applicationId": task.application_id,
        "interviewId": task.interview_id,
        "problemId": task.problem_id,
        "mockSessionId": task.mock_session_id,
    }


def plan_json(plan: Plan, task_source: SupabaseTaskSource) -> dict[str, Any]:
    by_id = {t.id: t for t in task_source.list_tasks()}
    return {
        "brief": plan.brief,
        "blocks": [
            {
                "taskId": b.task_id,
                "title": b.title,
                "start": b.start.isoformat(),
                "end": b.end.isoformat(),
                "category": by_id[b.task_id].category.value if b.task_id in by_id else None,
                "priority": by_id[b.task_id].priority.name if b.task_id in by_id else None,
            }
            for b in plan.blocks
        ],
        "unplaced": [task_json(t, task_source) for t in plan.unplaced],
    }


def application_json(application: Application) -> dict[str, Any]:
    return {
        "id": application.id,
        "company": application.company,
        "role": application.role,
        "stage": application.stage.value,
        "appliedAt": application.applied_at.isoformat() if application.applied_at else None,
        "nextInterviewAt": (
            application.next_interview_at.isoformat()
            if application.next_interview_at
            else None
        ),
        "notes": application.notes,
    }


def interview_json(
    interview: Interview, application_source: SupabaseApplicationSource
) -> dict[str, Any]:
    application = None
    with contextlib.suppress(KeyError):
        application = application_source.get_application(interview.application_id)
    return {
        "id": interview.id,
        "applicationId": interview.application_id,
        "company": application.company if application else None,
        "role": application.role if application else None,
        "category": interview.category.value,
        "scheduledAt": interview.scheduled_at.isoformat(),
        "notes": interview.notes,
        "syncedToCalendar": interview.google_event_id is not None,
        "googleEventOwned": interview.google_event_owned,
        "hidden": interview.hidden,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def problem_json(problem: Problem) -> dict[str, Any]:
    return {
        "id": problem.id,
        "number": problem.number,
        "slug": problem.slug,
        "title": problem.title,
        "url": problem.url,
        "difficulty": problem.difficulty.value,
        "status": problem.status.value,
        "confidence": problem.confidence,
        "notes": problem.notes,
        "starred": problem.starred,
        "tagIds": problem.tag_ids,
        "createdAt": _iso(problem.created_at),
        "updatedAt": _iso(problem.updated_at),
        "lastAttemptedAt": _iso(problem.last_attempted_at),
        "solvedAt": _iso(problem.solved_at),
    }


def solution_json(solution: Solution) -> dict[str, Any]:
    return {
        "id": solution.id,
        "problemId": solution.problem_id,
        "title": solution.title,
        "language": solution.language,
        "code": solution.code,
        "timeComplexity": solution.time_complexity,
        "spaceComplexity": solution.space_complexity,
        "explanation": solution.explanation,
        "isOptimal": solution.is_optimal,
        "createdAt": _iso(solution.created_at),
    }


def problem_tag_json(tag: ProblemTag, problem_count: int) -> dict[str, Any]:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "problemCount": problem_count,
    }


def mock_question_json(question: MockQuestion, times_seen: int = 1) -> dict[str, Any]:
    """``timesSeen`` counts this question plus every copy pointing at it."""
    return {
        "id": question.id,
        "source": question.source.value,
        "sourceUrl": question.source_url,
        "company": question.company,
        "role": question.role,
        "roundType": question.round_type.value,
        "title": question.title,
        "promptMd": question.prompt_md,
        "constraints": question.constraints,
        "followUps": question.follow_ups,
        "languageHint": question.language_hint,
        "originalText": question.original_text,
        "originalLanguage": question.original_language,
        "reportedOn": question.reported_on.isoformat() if question.reported_on else None,
        "canonicalId": question.canonical_id,
        "notes": question.notes,
        "timesSeen": times_seen,
        "createdAt": _iso(question.created_at),
        "updatedAt": _iso(question.updated_at),
    }


def mock_rubric_json(rubric: MockRubric) -> dict[str, Any]:
    return {
        "id": rubric.id,
        "name": rubric.name,
        "roundType": rubric.round_type.value if rubric.round_type else None,
        "criteria": [
            {"key": c.key, "title": c.title, "description": c.description, "weight": c.weight}
            for c in rubric.criteria
        ],
        "updatedAt": _iso(rubric.updated_at),
    }


def mock_guideline_json(guideline: MockGuideline) -> dict[str, Any]:
    return {
        "id": guideline.id,
        "name": guideline.name,
        "bodyMd": guideline.body_md,
        "updatedAt": _iso(guideline.updated_at),
    }


def scorecard_json(card: Scorecard) -> dict[str, Any]:
    return {
        "id": card.id,
        "sessionId": card.session_id,
        "overallScore": card.overall_score,
        "summary": card.summary,
        "criteria": [
            {
                "key": c.key,
                "title": c.title,
                "score": c.score,
                "evidence": [{"quote": e.quote, "verified": e.verified} for e in c.evidence],
                "improvement": c.improvement,
            }
            for c in card.criteria
        ],
        "strengths": card.strengths,
        "weakAreas": [
            {
                "title": w.title,
                "why": w.why,
                "taskName": w.task_name,
                "category": w.category.value,
                "estDurationMin": w.est_duration_min,
            }
            for w in card.weak_areas
        ],
        "graderModel": card.grader_model,
        "createdAt": _iso(card.created_at),
    }


def mock_session_json(session: MockSession, scorecard: Scorecard | None) -> dict[str, Any]:
    """List shape: the transcript is left out (it can be long); fetch one
    session for the full record."""
    return {
        "id": session.id,
        "title": session.title,
        "questionId": session.question_id,
        "rubricId": session.rubric_id,
        "guidelineId": session.guideline_id,
        "kind": session.kind.value,
        "status": session.status.value,
        "templateId": session.template_id,
        "pack": session.pack,
        "startedAt": _iso(session.started_at),
        "endedAt": _iso(session.ended_at),
        "overallScore": scorecard.overall_score if scorecard else None,
        "createdAt": _iso(session.created_at),
    }


def mock_event_json(event: MockEvent) -> dict[str, Any]:
    return {"kind": event.kind.value, "data": event.data, "at": _iso(event.at)}
