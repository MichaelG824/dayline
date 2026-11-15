"""What a candidate did in a live session, as text: the diff against the
starting repo, line counts per save, a compact timeline plus final test
results for the grader, and a staged round's interviewer chat as a transcript.

Pure functions over models - no I/O.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime

from dayline.models import MockEvent, MockEventKind, MockSession

MAX_DIFF_CHARS = 200_000
MAX_TIMELINE_LINES = 120
MAX_FAILURES_SHOWN = 10
# The interviewer chat: a transcript of its own, so not timeline lines.
CHAT_KINDS = frozenset({MockEventKind.INTERVIEWER_MESSAGE, MockEventKind.CANDIDATE_MESSAGE})


def file_diff(path: str, before: str | None, after: str | None) -> str:
    """Unified diff of one file; ``None`` means the file does not exist."""
    old = (before or "").splitlines(keepends=True)
    new = (after or "").splitlines(keepends=True)
    lines = difflib.unified_diff(
        old,
        new,
        fromfile=f"a/{path}" if before is not None else "/dev/null",
        tofile=f"b/{path}" if after is not None else "/dev/null",
    )
    # A last line without a newline would glue onto the next file's header.
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def repo_diff(start: dict[str, str], end: dict[str, str]) -> str:
    """Unified diff of every file that changed, was added, or was deleted."""
    parts = [
        file_diff(path, start.get(path), end.get(path))
        for path in sorted(start.keys() | end.keys())
        if start.get(path) != end.get(path)
    ]
    diff = "".join(parts)
    if len(diff) > MAX_DIFF_CHARS:
        return diff[:MAX_DIFF_CHARS] + "\n… (diff cut)\n"
    return diff


def line_changes(before: str | None, after: str) -> tuple[int, int]:
    """``(added, removed)`` line counts from ``before`` to ``after``."""
    added = removed = 0
    for line in difflib.ndiff((before or "").splitlines(), after.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def _clock(at: datetime | None, start: datetime | None) -> str:
    if at is None or start is None:
        return "--:--"
    seconds = max(0, int((at - start).total_seconds()))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _event_line(event: MockEvent, saves: int = 1) -> str:
    d = event.data
    if event.kind is MockEventKind.FILE_SAVED:
        times = f", {saves} saves" if saves > 1 else ""
        return f"saved {d.get('path')} (+{d.get('added', 0)} -{d.get('removed', 0)}{times})"
    if event.kind is MockEventKind.TESTS_RUN:
        return (
            f"ran tests: {d.get('status')} "
            f"({d.get('passed', 0)} passed, {d.get('failed', 0)} failed, "
            f"{d.get('errors', 0)} errors)"
        )
    if event.kind is MockEventKind.COMMAND_RUN:
        return f"ran in the terminal: {d.get('command')} (exit {d.get('exitCode')})"
    if event.kind is MockEventKind.STAGE_TESTS_RUN:
        return (
            f"ran stage {d.get('stage')}'s hidden tests: {d.get('status')} "
            f"({d.get('passed', 0)} passed, {d.get('failed', 0)} failed, "
            f"{d.get('errors', 0)} errors)"
        )
    if event.kind is MockEventKind.STAGE_PASSED:
        return f"passed stage {d.get('stage')}"
    if event.kind is MockEventKind.STAGE_SKIPPED:
        return f"skipped stage {d.get('stage')} without passing it"
    if event.kind is MockEventKind.SESSION_STARTED:
        return "session started"
    return "session ended"


@dataclass(slots=True)
class _Entry:
    """One timeline line: an event, or a run of saves to the same file."""

    event: MockEvent
    last_at: datetime | None
    saves: int = 1


def timeline(events: list[MockEvent], start: datetime | None) -> list[str]:
    """One line per event, ``mm:ss`` from the start. Back-to-back saves of the
    same file merge into one line (``mm:ss-mm:ss``, total line changes, save
    count) so autosave does not drown the record but the time spent shows."""
    entries: list[_Entry] = []
    for event in events:
        if event.kind in CHAT_KINDS:
            continue
        last = entries[-1] if entries else None
        if (
            last is not None
            and event.kind is MockEventKind.FILE_SAVED
            and last.event.kind is MockEventKind.FILE_SAVED
            and last.event.data.get("path") == event.data.get("path")
        ):
            for key in ("added", "removed"):
                last.event.data[key] = last.event.data.get(key, 0) + event.data.get(key, 0)
            last.last_at = event.at
            last.saves += 1
            continue
        copied = MockEvent(
            session_id=event.session_id, kind=event.kind, data=dict(event.data), at=event.at
        )
        entries.append(_Entry(event=copied, last_at=event.at))

    lines = []
    for entry in entries:
        when = _clock(entry.event.at, start)
        if entry.saves > 1:
            when += f"-{_clock(entry.last_at, start)}"
        lines.append(f"{when} {_event_line(entry.event, entry.saves)}")
    if len(lines) > MAX_TIMELINE_LINES:
        half = MAX_TIMELINE_LINES // 2
        lines = [*lines[:half], f"… {len(lines) - 2 * half} more …", *lines[-half:]]
    return lines


def chat_transcript(events: list[MockEvent], start: datetime | None) -> str:
    """A staged round's interviewer chat as ``[mm:ss] Speaker: text`` lines."""
    lines = []
    for event in events:
        if event.kind in CHAT_KINDS:
            who = "Interviewer" if event.kind is MockEventKind.INTERVIEWER_MESSAGE else "Candidate"
            lines.append(f"[{_clock(event.at, start)}] {who}: {event.data.get('text', '')}")
    return "\n".join(lines)


def tests_summary(report: dict[str, object] | None) -> str:
    if not report:
        return (
            "The Run tests button was never used; any test runs in the terminal "
            "are in the timeline."
        )
    head = (
        f"Last test run: {report.get('status')} - {report.get('passed', 0)} passed, "
        f"{report.get('failed', 0)} failed, {report.get('errors', 0)} errors"
    )
    cases = report.get("cases")
    failing = [
        c
        for c in (cases if isinstance(cases, list) else [])
        if isinstance(c, dict) and c.get("outcome") in ("failed", "error")
    ]
    lines = [head]
    for case in failing[:MAX_FAILURES_SHOWN]:
        message = str(case.get("message") or "").strip().splitlines()
        lines.append(f"- {case.get('name')}: {message[-1] if message else case.get('outcome')}")
    return "\n".join(lines)


def work_record(session: MockSession, events: list[MockEvent]) -> str:
    """Everything the candidate did, for the grader. Empty for pasted
    transcripts, which have no work record."""
    if not session.started_at and not events:
        return ""
    parts = [
        "## Timeline (mm:ss from the start)",
        "\n".join(timeline(events, session.started_at)) or "(no activity)",
        "## Tests",
        tests_summary(session.test_report),
        "## Diff against the starting repo",
        session.final_diff.strip() or "(no changes)",
    ]
    return "\n\n".join(parts)
