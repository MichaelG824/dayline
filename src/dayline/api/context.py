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

Importing this module constructs the context, which needs ``SUPABASE_URL`` and
``SUPABASE_SERVICE_ROLE_KEY`` in the environment (see ``.env.example``) - same
requirement the old ``api/main.py`` import carried.
"""

from __future__ import annotations

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
    anthropic_client: anthropic.Anthropic
    calendars: dict[date, InMemoryCalendar] = field(default_factory=dict)
    google_calendar: GoogleCalendarClient | None = None

    def calendar(self, day: date) -> InMemoryCalendar:
        if day not in self.calendars:
            self.calendars[day] = InMemoryCalendar()
        return self.calendars[day]


def build_context() -> AppContext:
    """Construct the single application context (Supabase-backed, live client)."""
    client = get_supabase_client()
    return AppContext(
        client=client,
        task_source=SupabaseTaskSource(client),
        application_source=SupabaseApplicationSource(client),
        interview_source=SupabaseInterviewSource(client),
        anthropic_client=anthropic.Anthropic(),
    )


# Single shared context for the process - constructed once at import, matching
# the old module-load behavior in api/main.py.
context = build_context()


def get_context() -> AppContext:
    """FastAPI-style accessor for the shared context (used by controllers/services)."""
    return context


# Annotated dependency the controllers use to inject the shared context - the
# modern FastAPI form (avoids a bare ``Depends()`` in argument defaults).
ContextDep = Annotated[AppContext, Depends(get_context)]
