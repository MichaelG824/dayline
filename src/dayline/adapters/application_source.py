"""Application source interface.

``ApplicationSource`` is the contract for reading and creating job
applications (the funnel entities interviews and prep tasks link to). Kept
stdlib-only, mirroring the ``TaskSource``/``CalendarClient`` pattern: only the
concrete Supabase implementation imports a third-party client.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from dayline.models import Application, ApplicationStage


@runtime_checkable
class ApplicationSource(Protocol):
    """Read/create surface over job applications."""

    def list_applications(self) -> list[Application]:
        """Return every application."""
        ...

    def get_application(self, application_id: str) -> Application:
        """Return a single application by id. Raises ``KeyError`` if absent."""
        ...

    def create_application(self, application: Application) -> Application:
        """Persist a new application; return it as stored."""
        ...


class InMemoryApplicationSource:
    """A fully working in-memory :class:`ApplicationSource` for tests and local
    runs - no network, no credentials."""

    def __init__(self, applications: list[Application] | None = None) -> None:
        self._applications: dict[str, Application] = {
            a.id: copy.deepcopy(a) for a in (applications or [])
        }

    def list_applications(self) -> list[Application]:
        result = list(self._applications.values())
        result.sort(key=lambda a: a.id)
        return [copy.deepcopy(a) for a in result]

    def get_application(self, application_id: str) -> Application:
        return copy.deepcopy(self._applications[application_id])

    def create_application(self, application: Application) -> Application:
        self._applications[application.id] = copy.deepcopy(application)
        return copy.deepcopy(application)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _application_to_row(application: Application) -> dict[str, Any]:
    return {
        "id": application.id,
        "company": application.company,
        "role": application.role,
        "stage": application.stage.value,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "next_interview_at": (
            application.next_interview_at.isoformat()
            if application.next_interview_at
            else None
        ),
        "notes": application.notes,
    }


def _row_to_application(row: dict[str, Any]) -> Application:
    stage = row.get("stage")
    return Application(
        id=row["id"],
        company=row["company"],
        role=row["role"],
        stage=ApplicationStage(stage) if stage else ApplicationStage.APPLIED,
        applied_at=_parse_dt(row.get("applied_at")),
        next_interview_at=_parse_dt(row.get("next_interview_at")),
        notes=row.get("notes"),
    )


class SupabaseApplicationSource:
    """Real Supabase-backed :class:`ApplicationSource`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def list_applications(self) -> list[Application]:
        resp = self._client.table("applications").select("*").execute()
        return [_row_to_application(row) for row in resp.data]

    def get_application(self, application_id: str) -> Application:
        resp = (
            self._client.table("applications")
            .select("*")
            .eq("id", application_id)
            .execute()
        )
        if not resp.data:
            raise KeyError(application_id)
        return _row_to_application(resp.data[0])

    def create_application(self, application: Application) -> Application:
        resp = (
            self._client.table("applications")
            .insert(_application_to_row(application))
            .execute()
        )
        return _row_to_application(resp.data[0])
