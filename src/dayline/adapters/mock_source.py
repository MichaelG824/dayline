"""Mock-interview source interface + in-memory fake + Supabase implementation.

``MockSource`` covers the tables behind the Mock tab: the private question bank,
rubrics, grading guidelines, practice sessions, and their scorecards. Kept
stdlib-only, mirroring the ``ProblemSource`` pattern: only the concrete
Supabase implementation talks to a third-party client.

Mock data never feeds ``build_plan`` - a weak area becomes an ordinary
:class:`~dayline.models.Task` (linked via ``Task.mock_session_id``) through the
chat confirm path.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, date, datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

from dayline.models import (
    Category,
    CriterionScore,
    Evidence,
    MockEvent,
    MockEventKind,
    MockGuideline,
    MockQuestion,
    MockQuestionSource,
    MockRoundType,
    MockRubric,
    MockSession,
    MockSessionKind,
    MockSessionStatus,
    RubricCriterion,
    Scorecard,
    WeakArea,
)


@runtime_checkable
class MockSource(Protocol):
    """Read/write surface over mock questions, rubrics, guidelines, sessions,
    and scorecards. ``get_*`` and ``update_*`` raise ``KeyError`` if absent;
    ``delete_*`` is a no-op if already gone."""

    def list_questions(self) -> list[MockQuestion]:
        """Every question, newest first."""
        ...

    def get_question(self, question_id: str) -> MockQuestion: ...

    def create_question(self, question: MockQuestion) -> MockQuestion: ...

    def update_question(self, question: MockQuestion) -> MockQuestion: ...

    def delete_question(self, question_id: str) -> None:
        """Delete a question; copies pointing at it become canonical."""
        ...

    def list_rubrics(self) -> list[MockRubric]:
        """Every rubric, alphabetical."""
        ...

    def get_rubric(self, rubric_id: str) -> MockRubric: ...

    def create_rubric(self, rubric: MockRubric) -> MockRubric: ...

    def update_rubric(self, rubric: MockRubric) -> MockRubric: ...

    def delete_rubric(self, rubric_id: str) -> None: ...

    def list_guidelines(self) -> list[MockGuideline]:
        """Every guideline, alphabetical."""
        ...

    def get_guideline(self, guideline_id: str) -> MockGuideline: ...

    def create_guideline(self, guideline: MockGuideline) -> MockGuideline: ...

    def update_guideline(self, guideline: MockGuideline) -> MockGuideline: ...

    def delete_guideline(self, guideline_id: str) -> None: ...

    def list_sessions(self) -> list[MockSession]:
        """Every session, newest first."""
        ...

    def get_session(self, session_id: str) -> MockSession: ...

    def create_session(self, session: MockSession) -> MockSession: ...

    def update_session(self, session: MockSession) -> MockSession: ...

    def delete_session(self, session_id: str) -> None:
        """Delete a session, its scorecards, and its events."""
        ...

    def add_event(self, event: MockEvent) -> MockEvent: ...

    def list_events(self, session_id: str) -> list[MockEvent]:
        """A session's events, oldest first."""
        ...

    def create_scorecard(self, scorecard: Scorecard) -> Scorecard: ...

    def latest_scorecards(self) -> dict[str, Scorecard]:
        """The newest scorecard per session id (sessions never graded are absent)."""
        ...


_T = TypeVar("_T")


def _created_key(item: Any) -> float:
    return item.created_at.timestamp() if item.created_at else 0.0


class InMemoryMockSource:
    """A fully working in-memory :class:`MockSource` for tests - no network,
    no credentials. Copies are returned on read so callers can't mutate
    internal state by accident."""

    def __init__(
        self,
        questions: list[MockQuestion] | None = None,
        rubrics: list[MockRubric] | None = None,
        guidelines: list[MockGuideline] | None = None,
        sessions: list[MockSession] | None = None,
    ) -> None:
        self._questions = {q.id: copy.deepcopy(q) for q in questions or []}
        self._rubrics = {r.id: copy.deepcopy(r) for r in rubrics or []}
        self._guidelines = {g.id: copy.deepcopy(g) for g in guidelines or []}
        self._sessions = {s.id: copy.deepcopy(s) for s in sessions or []}
        self._scorecards: list[Scorecard] = []
        self._events: list[MockEvent] = []

    @staticmethod
    def _stamp_new(item: _T) -> _T:
        stored: Any = copy.deepcopy(item)
        now = datetime.now(UTC)
        stored.created_at = stored.created_at or now
        if hasattr(stored, "updated_at"):
            stored.updated_at = now
        return stored  # type: ignore[no-any-return]

    @staticmethod
    def _stamp_update(item: _T, existing: _T) -> _T:
        stored: Any = copy.deepcopy(item)
        stored.created_at = getattr(existing, "created_at", None)
        stored.updated_at = datetime.now(UTC)
        return stored  # type: ignore[no-any-return]

    # Questions
    def list_questions(self) -> list[MockQuestion]:
        # Reversed insertion first so equal timestamps still sort newest-first.
        result = sorted(reversed(self._questions.values()), key=_created_key, reverse=True)
        return [copy.deepcopy(q) for q in result]

    def get_question(self, question_id: str) -> MockQuestion:
        return copy.deepcopy(self._questions[question_id])

    def create_question(self, question: MockQuestion) -> MockQuestion:
        stored = self._stamp_new(question)
        self._questions[stored.id] = stored
        return copy.deepcopy(stored)

    def update_question(self, question: MockQuestion) -> MockQuestion:
        stored = self._stamp_update(question, self._questions[question.id])
        self._questions[stored.id] = stored
        return copy.deepcopy(stored)

    def delete_question(self, question_id: str) -> None:
        self._questions.pop(question_id, None)
        for q in self._questions.values():
            if q.canonical_id == question_id:
                q.canonical_id = None

    # Rubrics
    def list_rubrics(self) -> list[MockRubric]:
        result = sorted(self._rubrics.values(), key=lambda r: r.name.lower())
        return [copy.deepcopy(r) for r in result]

    def get_rubric(self, rubric_id: str) -> MockRubric:
        return copy.deepcopy(self._rubrics[rubric_id])

    def create_rubric(self, rubric: MockRubric) -> MockRubric:
        stored = self._stamp_new(rubric)
        self._rubrics[stored.id] = stored
        return copy.deepcopy(stored)

    def update_rubric(self, rubric: MockRubric) -> MockRubric:
        stored = self._stamp_update(rubric, self._rubrics[rubric.id])
        self._rubrics[stored.id] = stored
        return copy.deepcopy(stored)

    def delete_rubric(self, rubric_id: str) -> None:
        self._rubrics.pop(rubric_id, None)

    # Guidelines
    def list_guidelines(self) -> list[MockGuideline]:
        result = sorted(self._guidelines.values(), key=lambda g: g.name.lower())
        return [copy.deepcopy(g) for g in result]

    def get_guideline(self, guideline_id: str) -> MockGuideline:
        return copy.deepcopy(self._guidelines[guideline_id])

    def create_guideline(self, guideline: MockGuideline) -> MockGuideline:
        stored = self._stamp_new(guideline)
        self._guidelines[stored.id] = stored
        return copy.deepcopy(stored)

    def update_guideline(self, guideline: MockGuideline) -> MockGuideline:
        stored = self._stamp_update(guideline, self._guidelines[guideline.id])
        self._guidelines[stored.id] = stored
        return copy.deepcopy(stored)

    def delete_guideline(self, guideline_id: str) -> None:
        self._guidelines.pop(guideline_id, None)

    # Sessions + scorecards
    def list_sessions(self) -> list[MockSession]:
        result = sorted(reversed(self._sessions.values()), key=_created_key, reverse=True)
        return [copy.deepcopy(s) for s in result]

    def get_session(self, session_id: str) -> MockSession:
        return copy.deepcopy(self._sessions[session_id])

    def create_session(self, session: MockSession) -> MockSession:
        stored = self._stamp_new(session)
        self._sessions[stored.id] = stored
        return copy.deepcopy(stored)

    def update_session(self, session: MockSession) -> MockSession:
        if session.id not in self._sessions:
            raise KeyError(session.id)
        stored = self._stamp_update(session, self._sessions[session.id])
        self._sessions[stored.id] = stored
        return copy.deepcopy(stored)

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._scorecards = [c for c in self._scorecards if c.session_id != session_id]
        self._events = [e for e in self._events if e.session_id != session_id]

    def add_event(self, event: MockEvent) -> MockEvent:
        if event.session_id not in self._sessions:
            raise KeyError(event.session_id)
        stored = copy.deepcopy(event)
        stored.id = stored.id or str(uuid.uuid4())
        stored.at = stored.at or datetime.now(UTC)
        self._events.append(stored)
        return copy.deepcopy(stored)

    def list_events(self, session_id: str) -> list[MockEvent]:
        events = [copy.deepcopy(e) for e in self._events if e.session_id == session_id]
        return sorted(events, key=lambda e: e.at or datetime.min.replace(tzinfo=UTC))

    def create_scorecard(self, scorecard: Scorecard) -> Scorecard:
        if scorecard.session_id not in self._sessions:
            raise KeyError(scorecard.session_id)
        stored = self._stamp_new(scorecard)
        self._scorecards.append(stored)
        return copy.deepcopy(stored)

    def latest_scorecards(self) -> dict[str, Scorecard]:
        latest: dict[str, Scorecard] = {}
        # Appended in creation order, so a later card always replaces an earlier one.
        for card in self._scorecards:
            latest[card.session_id] = copy.deepcopy(card)
        return latest


# --------------------------------------------------------------------------- #
# Supabase-backed MockSource
# --------------------------------------------------------------------------- #


def _parse_dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def _question_to_row(q: MockQuestion) -> dict[str, Any]:
    return {
        "id": q.id,
        "source": q.source.value,
        "source_url": q.source_url,
        "company": q.company,
        "role": q.role,
        "round_type": q.round_type.value,
        "title": q.title,
        "prompt_md": q.prompt_md,
        "constraints": q.constraints,
        "follow_ups": q.follow_ups,
        "language_hint": q.language_hint,
        "original_text": q.original_text,
        "original_language": q.original_language,
        "reported_on": q.reported_on.isoformat() if q.reported_on else None,
        "canonical_id": q.canonical_id,
        "notes": q.notes,
    }


def _row_to_question(row: dict[str, Any]) -> MockQuestion:
    return MockQuestion(
        id=row["id"],
        source=MockQuestionSource(row["source"]),
        source_url=row.get("source_url"),
        company=row.get("company"),
        role=row.get("role"),
        round_type=MockRoundType(row["round_type"]),
        title=row["title"],
        prompt_md=row.get("prompt_md") or "",
        constraints=list(row.get("constraints") or []),
        follow_ups=list(row.get("follow_ups") or []),
        language_hint=row.get("language_hint"),
        original_text=row.get("original_text") or "",
        original_language=row.get("original_language"),
        reported_on=_parse_date(row.get("reported_on")),
        canonical_id=row.get("canonical_id"),
        notes=row.get("notes") or "",
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _rubric_to_row(r: MockRubric) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "round_type": r.round_type.value if r.round_type else None,
        "criteria": [
            {"key": c.key, "title": c.title, "description": c.description, "weight": c.weight}
            for c in r.criteria
        ],
    }


def _row_to_rubric(row: dict[str, Any]) -> MockRubric:
    return MockRubric(
        id=row["id"],
        name=row["name"],
        round_type=MockRoundType(row["round_type"]) if row.get("round_type") else None,
        criteria=[
            RubricCriterion(
                key=c["key"],
                title=c.get("title") or c["key"],
                description=c.get("description") or "",
                weight=float(c.get("weight", 1)),
            )
            for c in row.get("criteria") or []
        ],
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _row_to_guideline(row: dict[str, Any]) -> MockGuideline:
    return MockGuideline(
        id=row["id"],
        name=row["name"],
        body_md=row.get("body_md") or "",
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _row_to_session(row: dict[str, Any]) -> MockSession:
    return MockSession(
        id=row["id"],
        title=row["title"],
        question_id=row.get("question_id"),
        rubric_id=row.get("rubric_id"),
        guideline_id=row.get("guideline_id"),
        transcript=row.get("transcript") or "",
        kind=MockSessionKind(row.get("kind") or MockSessionKind.TRANSCRIPT),
        status=MockSessionStatus(row.get("status") or MockSessionStatus.ENDED),
        template_id=row.get("template_id"),
        pack=row.get("pack"),
        started_at=_parse_dt(row.get("started_at")),
        ended_at=_parse_dt(row.get("ended_at")),
        final_files=dict(row.get("final_files") or {}),
        final_diff=row.get("final_diff") or "",
        test_report=row.get("test_report"),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _session_to_row(session: MockSession) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": session.id,
        "title": session.title,
        "question_id": session.question_id,
        "rubric_id": session.rubric_id,
        "guideline_id": session.guideline_id,
        "transcript": session.transcript,
    }
    # Only live sessions write the migration-012 columns, so pasted
    # transcripts keep working on a database that has only run 011.
    if session.kind is MockSessionKind.LIVE:
        row |= {
            "kind": session.kind.value,
            "status": session.status.value,
            "template_id": session.template_id,
            "pack": session.pack,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "final_files": session.final_files,
            "final_diff": session.final_diff,
            "test_report": session.test_report,
        }
    return row


def _row_to_event(row: dict[str, Any]) -> MockEvent:
    return MockEvent(
        id=row["id"],
        session_id=row["session_id"],
        kind=MockEventKind(row["kind"]),
        data=dict(row.get("data") or {}),
        at=_parse_dt(row.get("at")),
    )


def _scorecard_to_row(card: Scorecard) -> dict[str, Any]:
    return {
        "id": card.id,
        "session_id": card.session_id,
        "overall_score": card.overall_score,
        "summary": card.summary,
        "criteria": [
            {
                "key": c.key,
                "title": c.title,
                "score": c.score,
                "evidence": [{"quote": e.quote, "verified": e.verified} for e in c.evidence],
                "improvement": c.improvement,
            }
            for c in card.criteria
        ],
        "strengths": card.strengths,
        "weak_areas": [
            {
                "title": w.title,
                "why": w.why,
                "taskName": w.task_name,
                "category": w.category.value,
                "estDurationMin": w.est_duration_min,
            }
            for w in card.weak_areas
        ],
        "grader_model": card.grader_model,
    }


def _row_to_scorecard(row: dict[str, Any]) -> Scorecard:
    return Scorecard(
        id=row["id"],
        session_id=row["session_id"],
        overall_score=float(row["overall_score"]),
        summary=row.get("summary") or "",
        criteria=[
            CriterionScore(
                key=c["key"],
                title=c.get("title") or c["key"],
                score=int(c["score"]),
                evidence=[
                    Evidence(quote=e["quote"], verified=bool(e.get("verified")))
                    for e in c.get("evidence") or []
                ],
                improvement=c.get("improvement") or "",
            )
            for c in row.get("criteria") or []
        ],
        strengths=list(row.get("strengths") or []),
        weak_areas=[
            WeakArea(
                title=w["title"],
                why=w.get("why") or "",
                task_name=w["taskName"],
                category=Category(w["category"]),
                est_duration_min=int(w["estDurationMin"]),
            )
            for w in row.get("weak_areas") or []
        ],
        grader_model=row["grader_model"],
        created_at=_parse_dt(row.get("created_at")),
    )


class SupabaseMockSource:
    """Real Supabase-backed :class:`MockSource`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _get_one(self, table: str, row_id: str) -> dict[str, Any]:
        resp = self._client.table(table).select("*").eq("id", row_id).execute()
        if not resp.data:
            raise KeyError(row_id)
        return dict(resp.data[0])

    def _update(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row_id = row.pop("id")
        resp = self._client.table(table).update(row).eq("id", row_id).execute()
        if not resp.data:
            raise KeyError(row_id)
        return dict(resp.data[0])

    # Questions
    def list_questions(self) -> list[MockQuestion]:
        resp = (
            self._client.table("mock_questions")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return [_row_to_question(row) for row in resp.data]

    def get_question(self, question_id: str) -> MockQuestion:
        return _row_to_question(self._get_one("mock_questions", question_id))

    def create_question(self, question: MockQuestion) -> MockQuestion:
        resp = self._client.table("mock_questions").insert(_question_to_row(question)).execute()
        return _row_to_question(resp.data[0])

    def update_question(self, question: MockQuestion) -> MockQuestion:
        return _row_to_question(self._update("mock_questions", _question_to_row(question)))

    def delete_question(self, question_id: str) -> None:
        # Copies pointing here are un-linked by `on delete set null` (migration 011).
        self._client.table("mock_questions").delete().eq("id", question_id).execute()

    # Rubrics
    def list_rubrics(self) -> list[MockRubric]:
        resp = self._client.table("mock_rubrics").select("*").order("name").execute()
        return [_row_to_rubric(row) for row in resp.data]

    def get_rubric(self, rubric_id: str) -> MockRubric:
        return _row_to_rubric(self._get_one("mock_rubrics", rubric_id))

    def create_rubric(self, rubric: MockRubric) -> MockRubric:
        resp = self._client.table("mock_rubrics").insert(_rubric_to_row(rubric)).execute()
        return _row_to_rubric(resp.data[0])

    def update_rubric(self, rubric: MockRubric) -> MockRubric:
        return _row_to_rubric(self._update("mock_rubrics", _rubric_to_row(rubric)))

    def delete_rubric(self, rubric_id: str) -> None:
        self._client.table("mock_rubrics").delete().eq("id", rubric_id).execute()

    # Guidelines
    def list_guidelines(self) -> list[MockGuideline]:
        resp = self._client.table("mock_guidelines").select("*").order("name").execute()
        return [_row_to_guideline(row) for row in resp.data]

    def get_guideline(self, guideline_id: str) -> MockGuideline:
        return _row_to_guideline(self._get_one("mock_guidelines", guideline_id))

    def create_guideline(self, guideline: MockGuideline) -> MockGuideline:
        row = {"id": guideline.id, "name": guideline.name, "body_md": guideline.body_md}
        resp = self._client.table("mock_guidelines").insert(row).execute()
        return _row_to_guideline(resp.data[0])

    def update_guideline(self, guideline: MockGuideline) -> MockGuideline:
        row = {"id": guideline.id, "name": guideline.name, "body_md": guideline.body_md}
        return _row_to_guideline(self._update("mock_guidelines", row))

    def delete_guideline(self, guideline_id: str) -> None:
        self._client.table("mock_guidelines").delete().eq("id", guideline_id).execute()

    # Sessions + scorecards
    def list_sessions(self) -> list[MockSession]:
        resp = (
            self._client.table("mock_sessions").select("*").order("created_at", desc=True).execute()
        )
        return [_row_to_session(row) for row in resp.data]

    def get_session(self, session_id: str) -> MockSession:
        return _row_to_session(self._get_one("mock_sessions", session_id))

    def create_session(self, session: MockSession) -> MockSession:
        resp = self._client.table("mock_sessions").insert(_session_to_row(session)).execute()
        return _row_to_session(resp.data[0])

    def update_session(self, session: MockSession) -> MockSession:
        return _row_to_session(self._update("mock_sessions", _session_to_row(session)))

    def delete_session(self, session_id: str) -> None:
        # Scorecards and events cascade (migrations 011 and 012).
        self._client.table("mock_sessions").delete().eq("id", session_id).execute()

    def add_event(self, event: MockEvent) -> MockEvent:
        row: dict[str, Any] = {
            "session_id": event.session_id,
            "kind": event.kind.value,
            "data": event.data,
        }
        if event.at is not None:  # Events recorded after the fact keep their own time.
            row["at"] = event.at.isoformat()
        resp = self._client.table("mock_session_events").insert(row).execute()
        return _row_to_event(resp.data[0])

    def list_events(self, session_id: str) -> list[MockEvent]:
        resp = (
            self._client.table("mock_session_events")
            .select("*")
            .eq("session_id", session_id)
            .order("at")
            .execute()
        )
        return [_row_to_event(row) for row in resp.data]

    def create_scorecard(self, scorecard: Scorecard) -> Scorecard:
        resp = self._client.table("mock_scorecards").insert(_scorecard_to_row(scorecard)).execute()
        return _row_to_scorecard(resp.data[0])

    def latest_scorecards(self) -> dict[str, Scorecard]:
        resp = self._client.table("mock_scorecards").select("*").order("created_at").execute()
        # Ascending, so the newest card per session overwrites older ones.
        return {row["session_id"]: _row_to_scorecard(row) for row in resp.data}
