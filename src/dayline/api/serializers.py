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
from dayline.mock.staged import (
    StagedProblem,
    can_bring_early,
    focus_index,
    next_unlock,
    score_round,
)
from dayline.mock.worklog import ReplayEntry
from dayline.models import (
    Application,
    GeneratedProject,
    GenerationStatus,
    Interview,
    InterviewerStyle,
    MockEvent,
    MockEventKind,
    MockGuideline,
    MockQuestion,
    MockRubric,
    MockSession,
    MockSessionStatus,
    Plan,
    Problem,
    ProblemTag,
    Scorecard,
    Solution,
    StageStatus,
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
        "stagedProblemId": session.staged_problem_id,
        "stageCount": len(session.stages) if session.staged_problem_id else None,
        "stagesPassed": (
            sum(s.status is StageStatus.PASSED for s in session.stages)
            if session.staged_problem_id
            else None
        ),
        "createdAt": _iso(session.created_at),
    }


def mock_event_json(event: MockEvent) -> dict[str, Any]:
    data = event.data
    if event.kind is MockEventKind.ASSISTANT_EDIT_PROPOSED:
        # The full proposed file is only needed to apply it; the diff shows it.
        data = {k: v for k, v in data.items() if k != "content"}
    return {"kind": event.kind.value, "data": data, "at": _iso(event.at)}


def replay_json(
    session: MockSession, entries: list[ReplayEntry], now: datetime
) -> dict[str, Any]:
    """A live session's replay (``worklog.replay``): every moment with its
    offset from the start, plus the round's length and when the change
    request arrived, for the scrubber."""
    start = session.started_at
    end = session.ended_at or now
    arrived = next((e.t for e in entries if e.kind is MockEventKind.STAGE_UNLOCKED), None)
    last = max((e.t for e in entries if e.t is not None), default=0.0)
    return {
        "startedAt": _iso(start),
        "endedAt": _iso(session.ended_at),
        "durationS": max(last, (end - start).total_seconds() if start else 0.0),
        "changeRequestS": arrived,
        "entries": [
            {
                "t": e.t,
                "at": _iso(e.at),
                "group": e.group,
                "kind": e.kind.value,
                "title": e.title,
                "detail": e.detail,
                "diff": e.diff,
                "tone": e.tone,
                "stage": e.stage,
                "meta": e.meta,
            }
            for e in entries
        ],
    }


_CHAT_ROLES = {
    MockEventKind.INTERVIEWER_MESSAGE: "interviewer",
    MockEventKind.CANDIDATE_MESSAGE: "candidate",
}


def chat_json(events: list[MockEvent]) -> list[dict[str, Any]]:
    """A staged round's interviewer chat, oldest first."""
    return [
        {
            "role": _CHAT_ROLES[e.kind],
            "text": e.data.get("text", ""),
            "stage": e.data.get("stage"),
            "at": _iso(e.at),
        }
        for e in events
        if e.kind in _CHAT_ROLES
    ]


def staged_round_json(
    problem: StagedProblem, session: MockSession, events: list[MockEvent], now: datetime
) -> dict[str, Any]:
    """The candidate's view of a staged round. Hidden tests and interviewer
    notes never leave the server; a stage never reached shows only its number
    (so the problem can be practised again unspoiled), and a stage's edge
    cases stay hidden until it is over (their titles give the cases away).

    ``activeStage`` is the stage the candidate is in (in a timed round it can
    be a passed stage being polished until the change request arrives).
    ``changeRequest`` says when a timed stage is due, with the server's
    clock (``serverNow``) so the client can count down despite clock skew."""
    active = focus_index(session.stages)
    stages = []
    for stage, attempt, result in zip(
        problem.stages, session.stages, score_round(problem, session.stages, now), strict=True
    ):
        locked = attempt.status is StageStatus.LOCKED
        show_edges = attempt.status not in (StageStatus.ACTIVE, StageStatus.LOCKED)
        stages.append(
            {
                "number": stage.number,
                "title": None if locked else stage.title,
                "promptMd": None if locked else stage.prompt_md,
                "targetMin": None if locked else stage.target_min,
                "status": attempt.status.value,
                "startedAt": _iso(attempt.started_at),
                "finishedAt": _iso(attempt.finished_at),
                "timeSpentS": result.time_spent_s,
                "runs": attempt.runs,
                "report": attempt.report,
                "design": (
                    {"kept": result.design.kept, "verdict": result.design.verdict}
                    if result.design
                    else None
                ),
                "edgeCases": [
                    {"id": e.id, "title": e.title, "outcome": e.outcome}
                    for e in (result.edge_cases if show_edges else ())
                ],
            }
        )
    return {
        "problemId": problem.id,
        "activeStage": None if active is None else active + 1,
        "stages": stages,
        "chat": chat_json(events),
        "interviewerStyle": (session.interviewer_style or InterviewerStyle.COACH).value,
        "changeRequest": _change_request_json(problem, session, events),
        "canBringEarly": session.status is MockSessionStatus.LIVE
        and can_bring_early(problem, session.stages),
        "serverNow": _iso(now),
    }


def _change_request_json(
    problem: StagedProblem, session: MockSession, events: list[MockEvent]
) -> dict[str, Any] | None:
    """A timed round's change request: which stage, its minute, when it is
    due, and when it arrived (``None`` until it has)."""
    index = next((i for i, s in enumerate(problem.stages) if s.timed), None)
    if index is None or session.started_at is None:
        return None
    stage = problem.stages[index]
    attempt = session.stages[index]
    due = next_unlock(problem, session.stages, session.started_at)
    unlocked = next(
        (
            e
            for e in events
            if e.kind is MockEventKind.STAGE_UNLOCKED and e.data.get("stage") == index + 1
        ),
        None,
    )
    arrived = attempt.status is not StageStatus.LOCKED
    return {
        "stage": stage.number,
        "atMin": stage.unlock_min,
        "dueAt": _iso(due[1]) if due and due[0] == index else None,
        "arrivedAt": _iso(attempt.started_at) if arrived else None,
        "early": bool(unlocked and unlocked.data.get("early")),
    }


def generated_project_json(project: GeneratedProject, detail: bool = True) -> dict[str, Any]:
    """A generated project as the candidate sees it before the round. The
    hidden tests, reference solutions, interviewer notes and grader hints
    never leave the server; the change request's prompt is sent, and the
    client keeps it behind a reveal toggle. The attempt log is only shown
    for a generation that did not produce a project."""
    request = project.request
    artifact = project.artifact or {}
    data: dict[str, Any] = {
        "id": project.id,
        "status": project.status.value,
        "title": project.title,
        "summary": artifact.get("summary", ""),
        "stack": request.get("stack"),
        "difficulty": request.get("difficulty"),
        "durationMin": request.get("durationMin"),
        "changeRequestMin": request.get("changeRequestMin"),
        "prompt": request.get("prompt", ""),
        "progress": project.progress,
        "error": project.error,
        "createdAt": _iso(project.created_at),
        "finishedAt": _iso(project.finished_at),
    }
    if not detail:
        return data
    data |= {
        "feedback": request.get("feedback", ""),
        "contextFiles": [
            {"name": f["name"], "bytes": len(f["content"].encode())} for f in project.context_files
        ],
        "usage": project.usage,
        "log": project.log
        if project.status in (GenerationStatus.FAILED, GenerationStatus.CANCELLED)
        else [],
        "project": None,
    }
    if project.status is GenerationStatus.READY and artifact:
        task, change = artifact["task"], artifact["changeRequest"]
        data["project"] = {
            "openPath": artifact["openPath"],
            "files": artifact["files"],
            "task": {
                "title": task["title"],
                "promptMd": task["promptMd"],
                "targetMin": task["targetMin"],
            },
            "changeRequest": {
                "title": change["title"],
                "promptMd": change["promptMd"],
                "targetMin": change["targetMin"],
                "atMin": artifact["changeRequestMin"],
            },
        }
    return data
