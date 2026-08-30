"""Adapter interfaces and in-memory fakes.

The core and scheduler depend only on the :class:`TaskSource` and
:class:`CalendarClient` Protocols defined here - never on a concrete Notion or
Google implementation. The real adapters (a Notion MCP-backed ``TaskSource`` and
a direct Google Calendar ``CalendarClient``) drop in behind these interfaces
later without touching the core.
"""

from day_planner.adapters.calendar import (
    CalendarClient,
    GoogleCalendarClient,
    InMemoryCalendar,
)
from day_planner.adapters.task_source import (
    InMemoryTaskSource,
    NotionTaskSource,
    TaskSource,
)

__all__ = [
    "CalendarClient",
    "GoogleCalendarClient",
    "InMemoryCalendar",
    "InMemoryTaskSource",
    "NotionTaskSource",
    "TaskSource",
]
