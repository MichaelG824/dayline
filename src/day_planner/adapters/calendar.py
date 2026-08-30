"""Calendar client interface + in-memory fake.

``CalendarClient`` is the contract the scheduler uses to read busy time and write
plan blocks. Today only :class:`InMemoryCalendar` runs. Later a direct Google
Calendar caller will implement the same Protocol.

The interface carries just enough surface for **idempotent** write-back: besides
``list_busy`` and ``create_block`` it exposes ``list_events`` and
``delete_event`` so the scheduler can find and clear its *own* prior blocks (by a
stable title marker) before recreating them, instead of duplicating.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from day_planner.models import TimeSlot


@dataclass(slots=True, frozen=True)
class CalendarEvent:
    """A calendar event as seen by the client (enough to reconcile agent blocks)."""

    event_id: str
    title: str
    start: datetime
    end: datetime

    @property
    def slot(self) -> TimeSlot:
        return TimeSlot(self.start, self.end)


@runtime_checkable
class CalendarClient(Protocol):
    """Read/write surface over the calendar."""

    def list_busy(self, day: date) -> list[TimeSlot]:
        """Return busy intervals overlapping ``day``."""
        ...

    def list_events(self, day: date) -> list[CalendarEvent]:
        """Return full events overlapping ``day`` (used to reconcile agent blocks)."""
        ...

    def create_block(self, title: str, start: datetime, end: datetime) -> str:
        """Create a timed event; return its event id."""
        ...

    def delete_event(self, event_id: str) -> None:
        """Delete an event by id. No-op if it is already gone."""
        ...


class InMemoryCalendar:
    """A fully working in-memory :class:`CalendarClient` for tests, local runs,
    and the Streamlit dashboard - no network, no credentials.

    Seed it with pre-existing events (e.g. a recruiter call the planner must
    respect); the scheduler adds and reconciles its own blocks on top.
    """

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self._events: dict[str, CalendarEvent] = {}
        self._ids = itertools.count(1)
        for ev in events or []:
            self._events[ev.event_id] = ev

    def _overlaps_day(self, ev: CalendarEvent, day: date) -> bool:
        return ev.start.date() <= day <= (ev.end.date())

    def list_busy(self, day: date) -> list[TimeSlot]:
        return [
            ev.slot
            for ev in sorted(self._events.values(), key=lambda e: e.start)
            if self._overlaps_day(ev, day)
        ]

    def list_events(self, day: date) -> list[CalendarEvent]:
        return [
            ev
            for ev in sorted(self._events.values(), key=lambda e: e.start)
            if self._overlaps_day(ev, day)
        ]

    def create_block(self, title: str, start: datetime, end: datetime) -> str:
        event_id = f"evt-{next(self._ids)}"
        self._events[event_id] = CalendarEvent(event_id, title, start, end)
        return event_id

    def delete_event(self, event_id: str) -> None:
        self._events.pop(event_id, None)


class GoogleCalendarClient:
    """DEFERRED: real direct Google Calendar caller (the epic's baseline pattern).

    This will call the Google Calendar REST API directly (no MCP layer) to read
    busy/free and create timed blocks, satisfying :class:`CalendarClient`
    unchanged. It is intentionally *not* implemented in this increment: no OAuth
    credentials are available yet.

    Required when wired: a Google Cloud OAuth client (``credentials.json``) and a
    stored user token (``token.json``); install extras with
    ``pip install '.[google]'``.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "GoogleCalendarClient is deferred: it needs Google OAuth credentials "
            "(credentials.json / token.json) and the '.[google]' extra. Use "
            "InMemoryCalendar until those are provisioned. See README setup checklist."
        )
