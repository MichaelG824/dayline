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
    Plan,
    Problem,
    ProblemTag,
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
