"""Shared application context: the singleton adapters and mutable runtime state.

The old ``api/main.py`` held these as module-level globals. They now live in
one :class:`AppContext` so the thin routers and the services they call can all
share the same persistent Supabase sources, the day-keyed in-memory calendars,
and the single (reassignable) Google Calendar client.

Supabase is the source of truth for tasks/applications/interviews - these
sources are constructed once, not day-keyed fakes. The day-scheduling calendar
stays in-memory and day-keyed (task blocks are never written to a real
calendar - deliberate, see AGENTS.md). ``google_calendar`` starts ``None`` and
is set by ``POST /api/calendar/connect`` (see ``services/calendar.py``).

``get_context()`` constructs the context on first use, which needs
``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` in the environment (see
``.env.example``). Importing this module does not talk to Supabase, so auth
tests can mount the app without live credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Annotated

import anthropic
from dotenv import load_dotenv
from fastapi import Depends

if TYPE_CHECKING:
    from supabase import Client

load_dotenv()

from dayline.adapters.application_source import (  # noqa: E402
    SupabaseApplicationSource,
)
from dayline.adapters.calendar import GoogleCalendarClient, InMemoryCalendar  # noqa: E402
from dayline.adapters.interview_source import SupabaseInterviewSource  # noqa: E402
from dayline.adapters.mock_source import SupabaseMockSource  # noqa: E402
from dayline.adapters.problem_source import SupabaseProblemSource  # noqa: E402
from dayline.adapters.sandbox import SandboxClient, runner_from_env  # noqa: E402
from dayline.adapters.supabase_client import get_supabase_client  # noqa: E402
from dayline.adapters.task_source import SupabaseTaskSource  # noqa: E402

# How far ahead interview auto-discovery looks for calendar events to track.
INTERVIEW_DISCOVERY_WINDOW_DAYS = 30


@dataclass
class AppContext:
    """Persistent stores plus the reassignable Google Calendar client.

    ``google_calendar`` is the only mutable field: it starts ``None`` and is
    swapped in wholesale by the calendar-connect flow, so any service or router
    holding this shared context sees the connection immediately.
    """

    client: Client
    task_source: SupabaseTaskSource
    application_source: SupabaseApplicationSource
    interview_source: SupabaseInterviewSource
    problem_source: SupabaseProblemSource
    mock_source: SupabaseMockSource
    anthropic_client: anthropic.Anthropic
    # The sandbox runner for live mock sessions; None when SANDBOX_RUNNER_URL
    # is unset (live sessions are then unavailable, everything else works).
    sandbox: SandboxClient | None = None
    calendars: dict[date, InMemoryCalendar] = field(default_factory=dict)
    google_calendar: GoogleCalendarClient | None = None

    def calendar(self, day: date) -> InMemoryCalendar:
        if day not in self.calendars:
            self.calendars[day] = InMemoryCalendar()
        return self.calendars[day]


def _google_calendar_from_env() -> GoogleCalendarClient | None:
    """Use a stored refresh token when one is provided (production).

    Cloud Run / Render disks are ephemeral, so the desktop ``token.json`` flow
    cannot survive scale-to-zero. A refresh token in
    ``GOOGLE_CALENDAR_REFRESH_TOKEN`` (plus the web OAuth client id/secret)
    reconstructs the client at boot. Returns ``None`` when unset so local
    ``POST /api/calendar/connect`` still runs the desktop flow.
    """
    if not os.environ.get("GOOGLE_CALENDAR_REFRESH_TOKEN", "").strip():
        return None
    try:
        return GoogleCalendarClient()
    except (RuntimeError, OSError, ValueError):
        return None


def build_context() -> AppContext:
    """Construct the single application context (Supabase-backed, live client)."""
    client = get_supabase_client()
    return AppContext(
        client=client,
        task_source=SupabaseTaskSource(client),
        application_source=SupabaseApplicationSource(client),
        interview_source=SupabaseInterviewSource(client),
        problem_source=SupabaseProblemSource(client),
        mock_source=SupabaseMockSource(client),
        anthropic_client=anthropic.Anthropic(),
        sandbox=runner_from_env(),
        google_calendar=_google_calendar_from_env(),
    )


# Lazy: importing the API (and therefore this module) must not require live
# Supabase credentials. Tests override ``get_context``; uvicorn builds on first
# request that needs adapters.
_context: AppContext | None = None


def get_context() -> AppContext:
    """FastAPI-style accessor for the shared context (used by controllers/services)."""
    global _context
    if _context is None:
        _context = build_context()
    return _context


# Annotated dependency the controllers use to inject the shared context - the
# modern FastAPI form (avoids a bare ``Depends()`` in argument defaults).
ContextDep = Annotated[AppContext, Depends(get_context)]
