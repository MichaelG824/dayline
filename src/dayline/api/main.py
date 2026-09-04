"""FastAPI surface for Dayline - a thin interactive layer over the core.

This holds zero scheduling logic: it calls :func:`run_daily_plan` and
serializes the result as JSON for the Next.js frontend (``web/``). Tasks,
applications, and interviews are persisted in Supabase (see
``supabase/schema.sql`` + ``supabase/migrations/``); the day-scheduling
calendar stays an in-memory fake per day (writing planned task blocks to a
real calendar remains a separate, deferred step). A real Google Calendar is
wired in for interview sync and the calendar agenda view - see the
``/api/calendar/*`` endpoints below.

Run it with::

    uvicorn dayline.api.main:app --reload --port 8000

Requires ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` in the
environment (see ``.env.example``); ``ANTHROPIC_API_KEY`` additionally backs
the chat endpoints in ``api/chat.py``.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from dayline.adapters.application_source import (  # noqa: E402
    SupabaseApplicationSource,
)
from dayline.adapters.calendar import GoogleCalendarClient, InMemoryCalendar  # noqa: E402
from dayline.adapters.category_weights import (  # noqa: E402
    PREP_CATEGORIES,
    get_category_ranks,
    get_category_weights,
    set_category_ranks,
)
from dayline.adapters.interview_calendar_sync import (  # noqa: E402
    INTERVIEW_EVENT_DURATION_MIN,
    interview_event_title,
    sync_interview_event,
)
from dayline.adapters.interview_source import SupabaseInterviewSource  # noqa: E402
from dayline.adapters.supabase_client import get_supabase_client  # noqa: E402
from dayline.adapters.task_source import SupabaseTaskSource  # noqa: E402
from dayline.api.chat import apply_proposal, run_chat_turn  # noqa: E402
from dayline.models import (  # noqa: E402
    Application,
    ApplicationStage,
    Category,
    Interview,
    InterviewCategory,
    Plan,
    Priority,
    Recurrence,
    Status,
    Task,
    Weekday,
    Window,
)
from dayline.scheduler.run import AGENT_MARKER, run_daily_plan  # noqa: E402

app = FastAPI(title="Dayline API")

# How far ahead the calendar agenda view (GET /api/calendar/agenda) looks.
AGENDA_WINDOW_DAYS = 14

# The Next.js dev server runs on :3000; this API is single-user/local so an
# open CORS policy scoped to that one origin is enough (see AGENTS.md).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single persistent stores, constructed once - replaces the old per-day
# reseeded in-memory fakes. Supabase is the source of truth for
# tasks/applications/interviews now; the day-scheduling calendar stays
# in-memory and day-keyed (writing planned task blocks to a real calendar is
# a separate, still-deferred step - see AGENTS.md). A real Google Calendar
# is wired in for a narrower purpose: pushing interviews to it (see
# /api/calendar/* below and adapters/interview_calendar_sync.py).
_client = get_supabase_client()
_task_source = SupabaseTaskSource(_client)
_application_source = SupabaseApplicationSource(_client)
_interview_source = SupabaseInterviewSource(_client)
_calendars: dict[date, InMemoryCalendar] = {}
_anthropic_client = anthropic.Anthropic()
# Starts disconnected, unlike the singletons above - requires an explicit
# POST /api/calendar/connect (runs the OAuth flow) before interviews sync.
_google_calendar: GoogleCalendarClient | None = None


def _calendar(day: date) -> InMemoryCalendar:
    if day not in _calendars:
        _calendars[day] = InMemoryCalendar()
    return _calendars[day]


def _parse_category(value: str) -> Category:
    try:
        return Category(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown category {value!r}") from exc


def _parse_priority(value: str) -> Priority:
    try:
        return Priority[value]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown priority {value!r}") from exc


def _parse_status(value: str) -> Status:
    try:
        return Status(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown status {value!r}") from exc


def _parse_window(value: str) -> Window:
    try:
        return Window(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown window {value!r}") from exc


def _parse_recurrence(value: str) -> Recurrence:
    try:
        return Recurrence(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown recurrence {value!r}") from exc


def _parse_weekday(value: str) -> Weekday:
    try:
        return Weekday(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown weekday {value!r}") from exc


def _task_json(task: Task, task_source: SupabaseTaskSource) -> dict[str, Any]:
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
    }


def _plan_json(plan: Plan, task_source: SupabaseTaskSource) -> dict[str, Any]:
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
        "unplaced": [_task_json(t, task_source) for t in plan.unplaced],
    }


def _application_json(application: Application) -> dict[str, Any]:
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


def _interview_json(interview: Interview) -> dict[str, Any]:
    application = None
    with contextlib.suppress(KeyError):
        application = _application_source.get_application(interview.application_id)
    return {
        "id": interview.id,
        "applicationId": interview.application_id,
        "company": application.company if application else None,
        "role": application.role if application else None,
        "category": interview.category.value,
        "scheduledAt": interview.scheduled_at.isoformat(),
        "notes": interview.notes,
        "syncedToCalendar": interview.google_event_id is not None,
    }


@app.post("/api/plan")
def plan_day(day: date) -> dict[str, Any]:
    """Compute and commit the plan for ``day``.

    Each call reconciles rather than duplicates (including "Re-plan" clicks).
    """
    calendar = _calendar(day)
    plan = run_daily_plan(day, _task_source, calendar, interview_source=_interview_source)
    agent_blocks = [e for e in calendar.list_events(day) if e.title.startswith(AGENT_MARKER)]
    return {
        "day": day.isoformat(),
        **_plan_json(plan, _task_source),
        "agentBlockCount": len(agent_blocks),
    }


@app.get("/api/tasks")
def list_tasks(day: date) -> list[dict[str, Any]]:
    """All current tasks (with status/scheduled time)."""
    return [_task_json(t, _task_source) for t in _task_source.list_tasks()]


class TaskCreateRequest(BaseModel):
    name: str
    category: str
    estDurationMin: int
    priority: str | None = None
    plannedDate: str | None = None
    fixedTime: str | None = None
    preferredWindow: str | None = None
    dueDate: str | None = None
    recurs: str | None = None
    recurDay: str | None = None
    applicationId: str | None = None
    interviewId: str | None = None


@app.post("/api/tasks", status_code=201)
def create_task(body: TaskCreateRequest) -> dict[str, Any]:
    category = _parse_category(body.category)
    if body.priority is not None:
        priority = _parse_priority(body.priority)
    else:
        weights = get_category_weights(_client)
        priority = weights.get(category, Priority.P3)

    try:
        task = Task(
            id=str(uuid.uuid4()),
            name=body.name,
            category=category,
            priority=priority,
            est_duration_min=body.estDurationMin,
            # A recurring task's eligibility is driven by recurs/recur_day, not
            # planned_date - ignore planned_date when recurrence is set so the
            # two mechanisms can't conflict (see Task.planned_date docstring).
            planned_date=(
                date.fromisoformat(body.plannedDate)
                if body.plannedDate and not body.recurs
                else None
            ),
            fixed_time=datetime.fromisoformat(body.fixedTime) if body.fixedTime else None,
            preferred_window=(
                _parse_window(body.preferredWindow) if body.preferredWindow else None
            ),
            due_date=datetime.fromisoformat(body.dueDate) if body.dueDate else None,
            recurs=_parse_recurrence(body.recurs) if body.recurs else None,
            recur_day=_parse_weekday(body.recurDay) if body.recurDay else None,
            application_id=body.applicationId,
            interview_id=body.interviewId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    created = _task_source.create_task(task)
    return _task_json(created, _task_source)


class TaskUpdateRequest(BaseModel):
    estDurationMin: int | None = None
    priority: str | None = None
    plannedDate: str | None = None
    category: str | None = None
    status: str | None = None


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdateRequest) -> dict[str, Any]:
    try:
        updated = _task_source.update_task(
            task_id,
            status=_parse_status(body.status) if body.status else None,
            est_duration_min=body.estDurationMin,
            priority=_parse_priority(body.priority) if body.priority else None,
            planned_date=date.fromisoformat(body.plannedDate) if body.plannedDate else None,
            category=_parse_category(body.category) if body.category else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No task {task_id!r}") from exc
    return _task_json(updated, _task_source)


@app.get("/api/category-weights")
def get_category_weights_endpoint() -> list[dict[str, Any]]:
    ranks = get_category_ranks(_client)
    return [{"category": category.value, "rank": ranks[category]} for category in PREP_CATEGORIES]


class CategoryWeightItem(BaseModel):
    category: str
    rank: int


@app.put("/api/category-weights")
def put_category_weights(body: list[CategoryWeightItem]) -> list[dict[str, Any]]:
    mapping = {_parse_category(item.category): item.rank for item in body}
    set_category_ranks(_client, mapping)
    return get_category_weights_endpoint()


@app.post("/api/category-weights/apply")
def apply_category_weights() -> dict[str, int]:
    """Bulk-reprioritize every BACKLOG task to match the current category
    ranking. Explicit and opt-in - re-ranking weights alone never silently
    rewrites existing tasks (see ``adapters/category_weights.py``)."""
    weights = get_category_weights(_client)
    updated = 0
    for task in _task_source.list_tasks(status=Status.BACKLOG):
        new_priority = weights.get(task.category)
        if new_priority is not None and new_priority != task.priority:
            _task_source.update_task(task.id, priority=new_priority)
            updated += 1
    return {"updated": updated}


@app.get("/api/interviews")
def list_interviews(upcoming: bool = True) -> list[dict[str, Any]]:
    after = datetime.now() if upcoming else datetime.min
    return [_interview_json(i) for i in _interview_source.list_upcoming(after=after)]


class InterviewCreateRequest(BaseModel):
    applicationId: str
    category: str
    scheduledAt: str
    notes: str | None = None


@app.post("/api/interviews", status_code=201)
def create_interview(body: InterviewCreateRequest) -> dict[str, Any]:
    try:
        category = InterviewCategory(body.category)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unknown interview category {body.category!r}"
        ) from exc
    try:
        _application_source.get_application(body.applicationId)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"No application {body.applicationId!r}"
        ) from exc

    interview = Interview(
        id=str(uuid.uuid4()),
        application_id=body.applicationId,
        category=category,
        scheduled_at=datetime.fromisoformat(body.scheduledAt),
        notes=body.notes,
    )
    created = _interview_source.create_interview(interview)
    if _google_calendar is not None:
        # Best-effort: a calendar hiccup must never fail interview creation -
        # Supabase remains the source of truth.
        with contextlib.suppress(Exception):
            application = None
            with contextlib.suppress(KeyError):
                application = _application_source.get_application(created.application_id)
            event_id = sync_interview_event(_google_calendar, created, application)
            created = _interview_source.update_interview(created.id, google_event_id=event_id)
    return _interview_json(created)


@app.delete("/api/interviews/{interview_id}", status_code=204)
def delete_interview(interview_id: str) -> None:
    if _google_calendar is not None:
        with contextlib.suppress(KeyError):
            interview = _interview_source.get_interview(interview_id)
            if interview.google_event_id:
                with contextlib.suppress(Exception):
                    _google_calendar.delete_event(interview.google_event_id)
    _interview_source.delete_interview(interview_id)


@app.get("/api/calendar/status")
def calendar_status() -> dict[str, bool]:
    return {"connected": _google_calendar is not None}


@app.post("/api/calendar/connect")
def connect_calendar() -> dict[str, bool]:
    """Run the (one-time) Google OAuth flow and hold the connected client for
    the life of this process. Needs `credentials.json` at the repo root -
    see GOOGLE_SETUP.md."""
    global _google_calendar
    try:
        _google_calendar = GoogleCalendarClient()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"connected": True}


@app.post("/api/calendar/sync-interviews")
def sync_interviews() -> dict[str, int]:
    """Push every currently-upcoming interview to the connected calendar -
    backfills interviews created before the calendar was connected."""
    if _google_calendar is None:
        raise HTTPException(status_code=409, detail="Google Calendar is not connected yet.")
    synced = 0
    for interview in _interview_source.list_upcoming():
        application = None
        with contextlib.suppress(KeyError):
            application = _application_source.get_application(interview.application_id)
        event_id = sync_interview_event(_google_calendar, interview, application)
        _interview_source.update_interview(interview.id, google_event_id=event_id)
        synced += 1
    return {"synced": synced}


@app.get("/api/calendar/agenda")
def calendar_agenda() -> dict[str, Any]:
    """Chronological view of what's coming up: every tracked interview (local
    data, shown regardless of connection) plus - if connected - every other
    Google Calendar event in the same window. A synced interview's own
    calendar event is skipped from the Google side so it isn't shown twice."""
    today = date.today()
    end_day = today + timedelta(days=AGENDA_WINDOW_DAYS)

    interviews = [
        i for i in _interview_source.list_upcoming() if i.scheduled_at.date() <= end_day
    ]
    synced_event_ids = {i.google_event_id for i in interviews if i.google_event_id}

    items: list[dict[str, Any]] = []
    for interview in interviews:
        application = None
        with contextlib.suppress(KeyError):
            application = _application_source.get_application(interview.application_id)
        items.append(
            {
                "kind": "interview",
                "id": interview.id,
                "title": interview_event_title(interview, application),
                "start": interview.scheduled_at.isoformat(),
                "end": (
                    interview.scheduled_at
                    + timedelta(minutes=INTERVIEW_EVENT_DURATION_MIN)
                ).isoformat(),
                "category": interview.category.value,
                "company": application.company if application else None,
                "interviewId": interview.id,
            }
        )

    if _google_calendar is not None:
        for event in _google_calendar.list_events_range(today, end_day):
            if event.event_id in synced_event_ids:
                continue
            items.append(
                {
                    "kind": "event",
                    "id": event.event_id,
                    "title": event.title,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                    "category": None,
                    "company": None,
                    "interviewId": None,
                }
            )

    items.sort(key=lambda item: item["start"])
    return {"googleConnected": _google_calendar is not None, "items": items}


@app.get("/api/applications")
def list_applications() -> list[dict[str, Any]]:
    return [_application_json(a) for a in _application_source.list_applications()]


@app.get("/api/applications/{application_id}/interviews")
def list_application_interviews(application_id: str) -> list[dict[str, Any]]:
    return [_interview_json(i) for i in _interview_source.list_for_application(application_id)]


class ApplicationCreateRequest(BaseModel):
    company: str
    role: str
    stage: str | None = None
    appliedAt: str | None = None
    notes: str | None = None


@app.post("/api/applications", status_code=201)
def create_application(body: ApplicationCreateRequest) -> dict[str, Any]:
    try:
        stage = ApplicationStage(body.stage) if body.stage else ApplicationStage.APPLIED
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown stage {body.stage!r}") from exc

    application = Application(
        id=str(uuid.uuid4()),
        company=body.company,
        role=body.role,
        stage=stage,
        applied_at=datetime.fromisoformat(body.appliedAt) if body.appliedAt else None,
        notes=body.notes,
    )
    created = _application_source.create_application(application)
    return _application_json(created)


class ChatRequest(BaseModel):
    day: str
    message: str
    history: list[dict[str, Any]] | None = None


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict[str, Any]:
    """Ask the assistant to reason about today's plan. Never applies changes
    directly - see ``adapters/../api/chat.py`` for the propose/confirm split."""
    result = run_chat_turn(
        _anthropic_client,
        _task_source,
        date.fromisoformat(body.day),
        body.message,
        history=body.history,
    )
    return {
        "explanation": result.explanation,
        "proposals": result.proposals,
        "history": result.history,
    }


class ChatConfirmRequest(BaseModel):
    day: str
    proposals: list[dict[str, Any]]


@app.post("/api/chat/confirm")
def chat_confirm(body: ChatConfirmRequest) -> dict[str, Any]:
    """Apply the user-approved subset of a chat turn's proposals, then
    re-plan the day so the frontend can reuse its existing plan rendering."""
    applied = [apply_proposal(_task_source, p) for p in body.proposals]
    day = date.fromisoformat(body.day)
    plan_response = plan_day(day)
    return {"applied": applied, "plan": plan_response}
