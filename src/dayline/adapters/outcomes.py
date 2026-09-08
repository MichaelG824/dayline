"""Lightweight outcome log for chat retros (accept/reject, completions, overrides).

Plain functions + in-memory store - never auto-mutates ranks or durations.
The LLM may read recent outcomes via ``get_recent_outcomes`` and *propose*
nudges; confirm still required.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from supabase import Client

# Known event kinds - free string at the DB layer so new kinds don't need a migration.
OUTCOME_PROPOSAL_ACCEPTED = "proposal_accepted"
OUTCOME_PROPOSAL_REJECTED = "proposal_rejected"
OUTCOME_TASK_COMPLETED = "task_completed"
OUTCOME_TASK_SKIPPED = "task_skipped"
OUTCOME_DURATION_OVERRIDE = "duration_override"


@dataclass
class OutcomeEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "createdAt": self.created_at.isoformat(),
        }


class InMemoryOutcomesStore:
    """Test/local outcome log."""

    def __init__(self) -> None:
        self._events: list[OutcomeEvent] = []

    def log_outcome(self, kind: str, payload: dict[str, Any] | None = None) -> OutcomeEvent:
        event = OutcomeEvent(kind=kind, payload=dict(payload or {}))
        self._events.append(event)
        return deepcopy(event)

    def list_recent(self, *, limit: int = 20) -> list[OutcomeEvent]:
        ordered = sorted(self._events, key=lambda e: e.created_at, reverse=True)
        return [deepcopy(e) for e in ordered[:limit]]


def log_outcome(
    client: Client, kind: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Append one outcome row; return the stored JSON shape."""
    event_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "id": event_id,
        "kind": kind,
        "payload": dict(payload or {}),
    }
    resp = client.table("planner_outcomes").insert(cast(Any, row)).execute()
    rows = cast("list[dict[str, Any]]", resp.data or [])
    if rows:
        return _row_to_dict(rows[0])
    return {
        "id": event_id,
        "kind": kind,
        "payload": dict(payload or {}),
        "createdAt": datetime.now(UTC).isoformat(),
    }


def list_recent_outcomes(client: Client, *, limit: int = 20) -> list[dict[str, Any]]:
    """Newest-first outcome rows for chat retros."""
    resp = (
        client.table("planner_outcomes")
        .select("id,kind,payload,created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_row_to_dict(row) for row in cast("list[dict[str, Any]]", resp.data or [])]


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    created_at: str | None
    if isinstance(created, datetime):
        created_at = created.isoformat()
    elif created is None:
        created_at = None
    else:
        created_at = str(created)
    return {
        "id": row["id"],
        "kind": row["kind"],
        "payload": dict(row.get("payload") or {}),
        "createdAt": created_at,
    }
