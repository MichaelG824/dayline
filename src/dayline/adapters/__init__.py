"""Adapter interfaces, in-memory fakes, and Supabase-backed implementations.

The core and scheduler depend only on the :class:`TaskSource` and
:class:`CalendarClient` Protocols defined here - never on a concrete Supabase
or Google implementation.
"""

from dayline.adapters.calendar import (
    CalendarClient,
    GoogleCalendarClient,
    InMemoryCalendar,
)
from dayline.adapters.task_source import (
    InMemoryTaskSource,
    SupabaseTaskSource,
    TaskSource,
)

__all__ = [
    "CalendarClient",
    "GoogleCalendarClient",
    "InMemoryCalendar",
    "InMemoryTaskSource",
    "SupabaseTaskSource",
    "TaskSource",
]
