"""A recorded generated AI-assisted round, as the events a real session
leaves: the candidate explores with the assistant, plans, accepts two AI
edits (one in 4 seconds), passes the task at 09:30, idles until the change
request arrives at 25:00, asks the interviewer one clarifying question,
accepts a filtering edit in 2 seconds without planning, fixes a failing run,
and passes the change request at 37:00.

Shared by the metrics, replay, and opt-in real-model analysis tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from dayline.mock.staged import Stage, StagedProblem
from dayline.models import (
    MockEvent,
    MockEventKind,
    MockRoundType,
    MockSession,
    MockSessionKind,
    MockSessionStatus,
    StageAttempt,
    StageStatus,
)

T0 = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
SID = "recorded-round"
SERVICE = "api/src/notes/notes.service.ts"
DTO = "api/src/notes/create-note.dto.ts"
CONTROLLER = "api/src/notes/notes.controller.ts"


def _stage(number: int, title: str, prompt: str, unlock_min: int) -> Stage:
    return Stage(
        number=number,
        slug="task" if number == 1 else "change-request",
        title=title,
        target_min=25 if number == 1 else 20,
        prompt_md=prompt,
        notes_md="Probe how tags are normalised and where filtering lives.",
        tests={f"stage{number}.test.ts": ""},
        cases=frozenset(
            {(f"stage{number}", f"case {number}a"), (f"stage{number}", f"case {number}b")}
        ),
        unlock_min=unlock_min,
    )


PROBLEM = StagedProblem(
    id="gen-notes",
    title="Tagged notes board",
    pack="next-nest",
    round_type=MockRoundType.AI_ASSISTED_PROJECT,
    duration_min=45,
    summary="Add tags to a notes board, then filtering.",
    open_path="README.md",
    solution=(CONTROLLER, DTO, SERVICE),
    stages=(
        _stage(1, "Tag notes", "Let users add tags to a note; tags are trimmed and lowercased.", 0),
        _stage(2, "Filter by tag", "Product wants the notes list filterable by a tag.", 25),
    ),
    starter={"README.md": "# Notes board\n"},
    analysis_hints=(
        "Did they read the DTO and ValidationPipe setup before adding a field?",
        "Did they normalise tags in one place?",
    ),
)


def _at(clock: str) -> datetime:
    minutes, seconds = clock.split(":")
    return T0 + timedelta(minutes=int(minutes), seconds=int(seconds))


def _diff(path: str, old: str, new: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n-{old}\n+{new}\n"


def _report(*passing: int) -> dict[str, Any]:
    cases = [
        {
            "classname": f"stage{n}",
            "name": f"case {n}{x}",
            "outcome": "passed" if n in passing else "failed",
        }
        for n in (1, 2)
        for x in "ab"
    ]
    failed = sum(c["outcome"] == "failed" for c in cases)
    return {
        "status": "failed" if failed else "passed",
        "passed": len(cases) - failed,
        "failed": failed,
        "errors": 0,
        "cases": cases,
    }


_SCRIPT: list[tuple[str, MockEventKind, dict[str, Any]]] = [
    ("00:00", MockEventKind.SESSION_STARTED, {"stagedProblem": "gen-notes", "interviewerStyle": "realistic"}),
    ("00:05", MockEventKind.INTERVIEWER_MESSAGE, {"stage": 1, "trigger": "stage_start", "text": "Hi. The task is in front of you; ask me about requirements any time."}),
    ("01:10", MockEventKind.ASSISTANT_PROMPT, {"turn": 1, "mode": "ask", "text": "Walk me through how a note is created: `NotesService.create` and the DTO in api/src/notes."}),
    ("01:40", MockEventKind.ASSISTANT_RESPONSE, {"turn": 1, "mode": "ask", "status": "done", "durationMs": 21000, "tools": ["read api/src/notes/notes.service.ts"], "text": "Notes are created in NotesService.create after the ValidationPipe checks CreateNoteDto."}),
    ("03:30", MockEventKind.ASSISTANT_PROMPT, {"turn": 2, "mode": "plan", "text": "Plan adding a tags field to notes: DTO validation, normalising in the service, returning them."}),
    ("04:00", MockEventKind.ASSISTANT_RESPONSE, {"turn": 2, "mode": "plan", "status": "done", "durationMs": 18000, "tools": [], "text": "1. Add tags to CreateNoteDto. 2. Normalise in create. 3. Return tags."}),
    ("05:00", MockEventKind.ASSISTANT_PROMPT, {"turn": 3, "mode": "edit", "text": "Do steps 1 and 2: add `tags` to CreateNoteDto and normalise them in `NotesService.create`."}),
    ("05:40", MockEventKind.ASSISTANT_EDIT_PROPOSED, {"turn": 3, "proposalId": "p1", "path": SERVICE, "summary": "Normalise tags on create.", "newFile": False, "added": 20, "removed": 2, "diff": _diff(SERVICE, "create(dto) {", "create(dto) { const tags = normalise(dto.tags);")}),
    ("05:40", MockEventKind.ASSISTANT_EDIT_PROPOSED, {"turn": 3, "proposalId": "p2", "path": DTO, "summary": "Add tags to the DTO.", "newFile": False, "added": 4, "removed": 0, "diff": _diff(DTO, "title: string;", "title: string; tags?: string[];")}),
    ("05:44", MockEventKind.ASSISTANT_EDIT_DECIDED, {"proposalId": "p1", "path": SERVICE, "decision": "accepted", "reviewMs": 4000}),
    ("05:44", MockEventKind.FILE_SAVED, {"path": SERVICE, "added": 20, "removed": 2, "diff": _diff(SERVICE, "create(dto) {", "create(dto) { const tags = normalise(dto.tags);")}),
    ("06:30", MockEventKind.ASSISTANT_EDIT_DECIDED, {"proposalId": "p2", "path": DTO, "decision": "accepted", "reviewMs": 50000}),
    ("06:30", MockEventKind.FILE_SAVED, {"path": DTO, "added": 4, "removed": 0, "diff": _diff(DTO, "title: string;", "title: string; tags?: string[];")}),
    ("07:10", MockEventKind.TESTS_RUN, {"status": "failed", "passed": 6, "failed": 1, "errors": 0}),
    ("09:00", MockEventKind.FILE_SAVED, {"path": CONTROLLER, "added": 2, "removed": 1, "diff": _diff(CONTROLLER, "return note;", "return { ...note, tags: note.tags };")}),
    ("09:30", MockEventKind.STAGE_TESTS_RUN, {"stage": 1, "status": "passed", "passed": 2, "failed": 0, "errors": 0}),
    ("09:30", MockEventKind.STAGE_PASSED, {"stage": 1}),
    ("10:00", MockEventKind.PREVIEW_RELOADED, {"server": "web"}),
    ("25:00", MockEventKind.STAGE_UNLOCKED, {"stage": 2, "early": False}),
    ("25:20", MockEventKind.INTERVIEWER_MESSAGE, {"stage": 2, "trigger": "stage_start", "text": "OK, the PM just came back - people want to see only the notes with one tag. Can you add that?"}),
    ("26:40", MockEventKind.CANDIDATE_MESSAGE, {"stage": 2, "text": "Should an unknown tag return an empty list or a 404?"}),
    ("26:50", MockEventKind.INTERVIEWER_MESSAGE, {"stage": 2, "trigger": "message", "text": "An empty list. Unknown tags are not an error."}),
    ("27:30", MockEventKind.ASSISTANT_PROMPT, {"turn": 4, "mode": "edit", "text": "add filtering by tag"}),
    ("28:00", MockEventKind.ASSISTANT_EDIT_PROPOSED, {"turn": 4, "proposalId": "p3", "path": SERVICE, "summary": "Filter notes by tag.", "newFile": False, "added": 12, "removed": 1, "diff": _diff(SERVICE, "findAll() {", "findAll(tag?: string) { const wanted = tag;")}),
    ("28:02", MockEventKind.ASSISTANT_EDIT_DECIDED, {"proposalId": "p3", "path": SERVICE, "decision": "accepted", "reviewMs": 2000}),
    ("28:02", MockEventKind.FILE_SAVED, {"path": SERVICE, "added": 12, "removed": 1, "diff": _diff(SERVICE, "findAll() {", "findAll(tag?: string) { const wanted = tag;")}),
    ("33:00", MockEventKind.STAGE_TESTS_RUN, {"stage": 2, "status": "failed", "passed": 3, "failed": 1, "errors": 0}),
    ("36:00", MockEventKind.FILE_SAVED, {"path": SERVICE, "added": 1, "removed": 1, "diff": _diff(SERVICE, "const wanted = tag;", "const wanted = tag?.trim().toLowerCase();")}),
    ("37:00", MockEventKind.STAGE_TESTS_RUN, {"stage": 2, "status": "passed", "passed": 4, "failed": 0, "errors": 0}),
    ("37:00", MockEventKind.STAGE_PASSED, {"stage": 2}),
    ("44:00", MockEventKind.SESSION_ENDED, {"sandboxLost": False}),
]  # fmt: skip


def recorded_round() -> tuple[StagedProblem, MockSession, list[MockEvent]]:
    events = [MockEvent(SID, kind, dict(data), at=_at(clock)) for clock, kind, data in _SCRIPT]
    session = MockSession(
        id=SID,
        title=PROBLEM.title,
        kind=MockSessionKind.LIVE,
        status=MockSessionStatus.ENDED,
        pack=PROBLEM.pack,
        started_at=T0,
        ended_at=_at("44:00"),
        staged_problem_id=PROBLEM.id,
        stages=[
            StageAttempt(
                status=StageStatus.PASSED,
                started_at=T0,
                finished_at=_at("09:30"),
                runs=1,
                report=_report(1),
            ),
            StageAttempt(
                status=StageStatus.PASSED,
                started_at=_at("25:00"),
                finished_at=_at("37:00"),
                runs=2,
                report=_report(1, 2),
            ),
        ],
        final_diff=_diff(SERVICE, "findAll() {", "findAll(tag?: string) {"),
        transcript="",
    )
    return PROBLEM, session, events
