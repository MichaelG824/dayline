"""Interview source interface.

``InterviewSource`` is the contract for reading and creating interview rounds.
Kept stdlib-only, mirroring the ``TaskSource``/``CalendarClient`` pattern: only
the concrete Supabase implementation imports a third-party client.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from dayline.models import Interview, InterviewCategory


@runtime_checkable
class InterviewSource(Protocol):
    """Read/create/update surface over interview rounds."""

    def list_upcoming(self, *, after: datetime | None = None) -> list[Interview]:
        """Return interviews at or after ``after`` (default: now), soonest first."""
        ...

    def get_interview(self, interview_id: str) -> Interview:
        """Return a single interview by id. Raises ``KeyError`` if absent."""
        ...

    def create_interview(self, interview: Interview) -> Interview:
        """Persist a new interview; return it as stored."""
        ...

    def list_for_application(self, application_id: str) -> list[Interview]:
        """Return every interview round for one application."""
        ...

    def delete_interview(self, interview_id: str) -> None:
        """Delete an interview by id. No-op if it is already gone."""
        ...

    def update_interview(self, interview_id: str, *, google_event_id: str | None) -> Interview:
        """Update the linked Google Calendar event id (``None`` clears it)."""
        ...


class InMemoryInterviewSource:
    """A fully working in-memory :class:`InterviewSource` for tests and local
    runs - no network, no credentials."""

    def __init__(self, interviews: list[Interview] | None = None) -> None:
        self._interviews: dict[str, Interview] = {
            i.id: copy.deepcopy(i) for i in (interviews or [])
        }

    def list_upcoming(self, *, after: datetime | None = None) -> list[Interview]:
        cutoff = after or datetime.now()
        result = [i for i in self._interviews.values() if i.scheduled_at >= cutoff]
        result.sort(key=lambda i: i.scheduled_at)
        return [copy.deepcopy(i) for i in result]

    def get_interview(self, interview_id: str) -> Interview:
        return copy.deepcopy(self._interviews[interview_id])

    def create_interview(self, interview: Interview) -> Interview:
        self._interviews[interview.id] = copy.deepcopy(interview)
        return copy.deepcopy(interview)

    def list_for_application(self, application_id: str) -> list[Interview]:
        result = [
            i for i in self._interviews.values() if i.application_id == application_id
        ]
        result.sort(key=lambda i: i.scheduled_at)
        return [copy.deepcopy(i) for i in result]

    def delete_interview(self, interview_id: str) -> None:
        self._interviews.pop(interview_id, None)

    def update_interview(self, interview_id: str, *, google_event_id: str | None) -> Interview:
        interview = self._interviews[interview_id]
        interview.google_event_id = google_event_id
        return copy.deepcopy(interview)


def _parse_dt(value: Any) -> datetime:
    return datetime.fromisoformat(value)


def _interview_to_row(interview: Interview) -> dict[str, Any]:
    return {
        "id": interview.id,
        "application_id": interview.application_id,
        "category": interview.category.value,
        "scheduled_at": interview.scheduled_at.isoformat(),
        "notes": interview.notes,
        "google_event_id": interview.google_event_id,
    }


def _row_to_interview(row: dict[str, Any]) -> Interview:
    return Interview(
        id=row["id"],
        application_id=row["application_id"],
        category=InterviewCategory(row["category"]),
        scheduled_at=_parse_dt(row["scheduled_at"]),
        notes=row.get("notes"),
        google_event_id=row.get("google_event_id"),
    )


class SupabaseInterviewSource:
    """Real Supabase-backed :class:`InterviewSource`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def list_upcoming(self, *, after: datetime | None = None) -> list[Interview]:
        cutoff = after or datetime.now()
        resp = (
            self._client.table("interviews")
            .select("*")
            .gte("scheduled_at", cutoff.isoformat())
            .order("scheduled_at")
            .execute()
        )
        return [_row_to_interview(row) for row in resp.data]

    def get_interview(self, interview_id: str) -> Interview:
        resp = (
            self._client.table("interviews")
            .select("*")
            .eq("id", interview_id)
            .execute()
        )
        if not resp.data:
            raise KeyError(interview_id)
        return _row_to_interview(resp.data[0])

    def create_interview(self, interview: Interview) -> Interview:
        resp = (
            self._client.table("interviews")
            .insert(_interview_to_row(interview))
            .execute()
        )
        return _row_to_interview(resp.data[0])

    def list_for_application(self, application_id: str) -> list[Interview]:
        resp = (
            self._client.table("interviews")
            .select("*")
            .eq("application_id", application_id)
            .order("scheduled_at")
            .execute()
        )
        return [_row_to_interview(row) for row in resp.data]

    def delete_interview(self, interview_id: str) -> None:
        self._client.table("interviews").delete().eq("id", interview_id).execute()

    def update_interview(self, interview_id: str, *, google_event_id: str | None) -> Interview:
        resp = (
            self._client.table("interviews")
            .update({"google_event_id": google_event_id})
            .eq("id", interview_id)
            .execute()
        )
        if not resp.data:
            raise KeyError(interview_id)
        return _row_to_interview(resp.data[0])
