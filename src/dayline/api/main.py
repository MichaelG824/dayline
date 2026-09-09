"""FastAPI app factory for Dayline - a thin interactive layer over the core.

This module holds zero scheduling and zero orchestration logic: it just builds
the ``FastAPI`` app, configures CORS, and mounts the domain controllers. Each
controller (``api/controllers/*.py``) is HTTP-only - path, status codes, and
request models - and delegates to a service (``api/services/*.py``) that talks
to the adapters/planner. Shared singletons (the Supabase sources, the day-keyed
in-memory calendars, the optional Google Calendar client) live on the
:class:`~dayline.api.context.AppContext` in ``api/context.py``.

Tasks, applications, and interviews are persisted in Supabase (see
``supabase/schema.sql`` + ``supabase/migrations/``); the day-scheduling calendar
stays an in-memory fake per day - task blocks live entirely in the app and are
never written to a real calendar (deliberate: tasks are Dayline's own scheduling
detail). A real Google Calendar is wired in for interviews only - see the
``/api/calendar/*`` endpoints.

Run it with::

    uvicorn dayline.api.main:app --reload --port 8000

Requires ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` in the environment
(see ``.env.example``); ``ANTHROPIC_API_KEY`` additionally backs the chat
endpoints in ``api/chat.py``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dayline.api.controllers import (
    applications,
    calendar,
    category_weights,
    chat,
    interviews,
    outcomes,
    plan,
    preferences,
    tasks,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Dayline API")

    # Next.js often lands on :3000, :3003, or :3004 when ports are taken; list
    # common localhost/127.0.0.1 origins so browser fetch to /api/chat is not
    # CORS-blocked (single-user local API - see AGENTS.md).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:3003",
            "http://localhost:3004",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3003",
            "http://127.0.0.1:3004",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for controller in (
        plan,
        tasks,
        category_weights,
        interviews,
        calendar,
        applications,
        chat,
        preferences,
        outcomes,
    ):
        app.include_router(controller.router)

    return app


app = create_app()
