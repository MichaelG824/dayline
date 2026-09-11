"""FastAPI app factory for Dayline - a thin interactive layer over the core.

This module holds zero scheduling and zero orchestration logic: it just builds
the ``FastAPI`` app, configures CORS + the auth gate, and mounts the domain
controllers. Each controller (``api/controllers/*.py``) is HTTP-only - path,
status codes, and request models - and delegates to a service
(``api/services/*.py``) that talks to the adapters/planner. Shared singletons
(the Supabase sources, the day-keyed in-memory calendars, the optional Google
Calendar client) live on the :class:`~dayline.api.context.AppContext` in
``api/context.py``.

Tasks, applications, and interviews are persisted in Supabase (see
``supabase/schema.sql`` + ``supabase/migrations/``); the day-scheduling calendar
stays an in-memory fake per day - task blocks live entirely in the app and are
never written to a real calendar (deliberate: tasks are Dayline's own scheduling
detail). A real Google Calendar is wired in for interviews only - see the
``/api/calendar/*`` endpoints.

Every ``/api/*`` route except ``/api/health`` and ``/api/auth/*`` requires a
Google-proven session whose email matches ``ALLOWED_EMAIL``. See
``api/auth.py``.

Run it with::

    uvicorn dayline.api.main:app --reload --port 8000

Requires ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` in the environment
(see ``.env.example``); ``ANTHROPIC_API_KEY`` additionally backs the chat
endpoints in ``api/chat.py``. ``AUTH_SECRET`` + Google OAuth client env vars
are required for sign-in.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dayline.api.auth import AuthGateMiddleware, cors_origins
from dayline.api.controllers import (
    applications,
    auth,
    calendar,
    category_weights,
    chat,
    health,
    interviews,
    outcomes,
    plan,
    preferences,
    tasks,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Dayline API")

    # Auth is inner; CORS is added last so it is the outermost middleware and
    # can answer OPTIONS preflights without a session. Credentials must be on
    # so the browser sends the session cookie on cross-origin local fetches.
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for controller in (
        health,
        auth,
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
