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
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from dayline.models import TimeSlot

# OAuth scope: full calendar access (read busy time + create/delete our blocks).
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]


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

    def list_events_range(self, start_day: date, end_day: date) -> list[CalendarEvent]:
        """Return full events overlapping ``[start_day, end_day]`` (inclusive),
        soonest first. Used to find calendar events importable as interviews."""
        ...

    def create_block(self, title: str, start: datetime, end: datetime) -> str:
        """Create a timed event; return its event id."""
        ...

    def update_event(self, event_id: str, title: str, start: datetime, end: datetime) -> None:
        """Update an existing event's title/time in place, leaving every
        other field (attendees, location, description, video links, ...)
        untouched. Never delete-and-recreate here: the event may be one the
        app only *linked to* (an imported interview) rather than created, and
        deleting someone else's real calendar event to replace it with a bare
        placeholder is destructive and irreversible."""
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

    def _overlaps_range(self, ev: CalendarEvent, start_day: date, end_day: date) -> bool:
        return ev.start.date() <= end_day and start_day <= ev.end.date()

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

    def list_events_range(self, start_day: date, end_day: date) -> list[CalendarEvent]:
        return [
            ev
            for ev in sorted(self._events.values(), key=lambda e: e.start)
            if self._overlaps_range(ev, start_day, end_day)
        ]

    def create_block(self, title: str, start: datetime, end: datetime) -> str:
        event_id = f"evt-{next(self._ids)}"
        self._events[event_id] = CalendarEvent(event_id, title, start, end)
        return event_id

    def update_event(self, event_id: str, title: str, start: datetime, end: datetime) -> None:
        if event_id in self._events:
            self._events[event_id] = CalendarEvent(event_id, title, start, end)

    def delete_event(self, event_id: str) -> None:
        self._events.pop(event_id, None)


def _to_rfc3339(dt: datetime, tz: str) -> str:
    """Naive local datetime -> attach ``tz`` and return an RFC3339 string.

    An already-aware ``dt`` (e.g. read back from a Postgres ``timestamptz``
    column, which always round-trips as aware) is *converted* into ``tz``
    instead - relabeling it with ``.replace()`` would silently corrupt the
    wall-clock time by the zone's UTC offset (caught via a real calendar
    event landing 5 hours off).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo(tz)).isoformat()
    return dt.astimezone(ZoneInfo(tz)).isoformat()


def _parse_google_dt(node: dict[str, Any], tz: str) -> datetime | None:
    """Parse a Google event ``start``/``end`` node into a naive local datetime.

    Returns ``None`` for all-day events (a ``date`` node with no ``dateTime``),
    which the planner ignores as busy time.
    """
    value = node.get("dateTime")
    if not value:
        return None
    aware = datetime.fromisoformat(value)
    return aware.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


class GoogleCalendarClient:
    """Real Google Calendar :class:`CalendarClient` - a direct REST caller (no MCP).

    Reads busy time and creates/reconciles the planner's timed blocks. Satisfies
    the :class:`CalendarClient` Protocol, so it drops into the scheduler unchanged
    in place of :class:`InMemoryCalendar`.

    Needs the ``google`` extra: ``pip install '.[google]'``. On first use it runs
    the Google OAuth consent flow in a browser and stores ``token.json``; after
    that it refreshes silently. See ``GOOGLE_SETUP.md``.

    Args:
        calendar_id: which calendar to plan into (default your primary calendar).
        credentials_path / token_path: OAuth client secret and stored token
            (default ``credentials.json`` / ``token.json`` at the repo root).
        timezone: IANA tz for created blocks; defaults to the calendar's own.
    """

    def __init__(
        self,
        *,
        calendar_id: str = "primary",
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        timezone: str | None = None,
    ) -> None:
        try:
            from googleapiclient.discovery import build
        except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "GoogleCalendarClient needs the Google client libraries. Install "
                "the extra: pip install '.[google]'."
            ) from exc
        self._calendar_id = calendar_id
        self._creds = self._load_credentials(credentials_path, token_path)
        self._service = build("calendar", "v3", credentials=self._creds)
        self._tz = timezone or self._detect_timezone()

    @property
    def timezone(self) -> str:
        """IANA tz name events are read/written in - callers that need to
        serialize a :class:`CalendarEvent`'s naive local time unambiguously
        (e.g. across a wire boundary) must attach this before doing so; see
        ``api/main.py``'s calendar-import endpoint."""
        return self._tz

    # --- CalendarClient Protocol --------------------------------------------
    def _execute(self, request: Any) -> Any:
        # googleapiclient's underlying httplib2.Http transport isn't
        # thread-safe; FastAPI runs sync endpoints in a thread pool, so two
        # concurrent calls sharing one transport can corrupt each other's
        # connection (observed as SSLError: RECORD_LAYER_FAILURE). Google's
        # own guidance is a fresh Http() per request - see
        # https://googleapis.github.io/google-api-python-client/docs/thread_safety.html
        # A plain httplib2.Http() carries no credentials, so wrap it with
        # AuthorizedHttp (the same bridge googleapiclient uses internally) to
        # keep requests authenticated.
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp

        return request.execute(http=AuthorizedHttp(self._creds, http=httplib2.Http()))

    def _list_events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        items = self._execute(
            self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=_to_rfc3339(start, self._tz),
                timeMax=_to_rfc3339(end, self._tz),
                singleEvents=True,
                orderBy="startTime",
            )
        ).get("items", [])
        events: list[CalendarEvent] = []
        for item in items:
            s = _parse_google_dt(item.get("start", {}), self._tz)
            e = _parse_google_dt(item.get("end", {}), self._tz)
            if s is None or e is None:
                continue  # skip all-day / malformed events
            events.append(CalendarEvent(item["id"], item.get("summary", ""), s, e))
        return events

    def list_events(self, day: date) -> list[CalendarEvent]:
        start = datetime.combine(day, time.min)
        return self._list_events_between(start, start + timedelta(days=1))

    def list_events_range(self, start_day: date, end_day: date) -> list[CalendarEvent]:
        start = datetime.combine(start_day, time.min)
        end = datetime.combine(end_day, time.min) + timedelta(days=1)
        return self._list_events_between(start, end)

    def list_busy(self, day: date) -> list[TimeSlot]:
        return [ev.slot for ev in self.list_events(day)]

    def create_block(self, title: str, start: datetime, end: datetime) -> str:
        body = {
            "summary": title,
            "start": {"dateTime": _to_rfc3339(start, self._tz), "timeZone": self._tz},
            "end": {"dateTime": _to_rfc3339(end, self._tz), "timeZone": self._tz},
        }
        event = self._execute(
            self._service.events().insert(calendarId=self._calendar_id, body=body)
        )
        return str(event["id"])

    def update_event(self, event_id: str, title: str, start: datetime, end: datetime) -> None:
        # events().patch (not update/insert) only touches the fields given,
        # leaving attendees/location/description/etc. on the existing event
        # untouched - required for imported interviews, whose event the app
        # never created and must not otherwise disturb.
        body = {
            "summary": title,
            "start": {"dateTime": _to_rfc3339(start, self._tz), "timeZone": self._tz},
            "end": {"dateTime": _to_rfc3339(end, self._tz), "timeZone": self._tz},
        }
        self._execute(
            self._service.events().patch(
                calendarId=self._calendar_id, eventId=event_id, body=body
            )
        )

    def delete_event(self, event_id: str) -> None:
        from googleapiclient.errors import HttpError

        try:
            self._execute(
                self._service.events().delete(
                    calendarId=self._calendar_id, eventId=event_id
                )
            )
        except HttpError as exc:
            if exc.resp.status not in (404, 410):  # already gone is fine
                raise

    # --- OAuth / setup -------------------------------------------------------
    def _load_credentials(
        self, credentials_path: str | Path | None, token_path: str | Path | None
    ) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        repo_root = Path(__file__).resolve().parents[3]
        cred_file = (
            Path(credentials_path) if credentials_path else repo_root / "credentials.json"
        )
        token_file = Path(token_path) if token_path else repo_root / "token.json"

        creds = None
        if token_file.exists():
            # google-auth ships no py.typed marker, so this call is reported
            # as untyped even under our ignore_missing_imports override above
            # (which only covers unresolved imports, not untyped calls).
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                str(token_file), GOOGLE_SCOPES
            )
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_file.exists():
                raise RuntimeError(
                    f"Missing Google OAuth client secret at {cred_file}. Download it "
                    "from the Google Cloud Console (OAuth client, 'Desktop app') and "
                    "save it there. See GOOGLE_SETUP.md."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json())
        return creds

    def _detect_timezone(self) -> str:
        try:
            cal = self._execute(self._service.calendars().get(calendarId=self._calendar_id))
            return str(cal.get("timeZone", "UTC"))
        except Exception:
            return "UTC"
