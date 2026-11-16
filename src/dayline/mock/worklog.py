"""What a candidate did in a live session, as text: the diff against the
starting repo, line counts per save, a compact timeline plus final test
results for the grader, a staged round's interviewer chat as a transcript,
a compact log of how the candidate used the AI assistant, and the full
replay of the round for the session page (:func:`replay`).

Pure functions over models - no I/O.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from dayline.models import MockEvent, MockEventKind, MockSession

MAX_DIFF_CHARS = 200_000
MAX_SAVE_DIFF_CHARS = 20_000
MAX_TIMELINE_LINES = 120
MAX_FAILURES_SHOWN = 10
# The interviewer chat: a transcript of its own, so not timeline lines.
CHAT_KINDS = frozenset({MockEventKind.INTERVIEWER_MESSAGE, MockEventKind.CANDIDATE_MESSAGE})
# Detailed in the AI-assistant log; the timeline keeps prompts and decisions.
AI_DETAIL_KINDS = frozenset(
    {MockEventKind.ASSISTANT_RESPONSE, MockEventKind.ASSISTANT_EDIT_PROPOSED}
)
MAX_AI_TURNS_SHOWN = 40
MAX_AI_PROMPT_CHARS = 500
MAX_AI_REPLY_CHARS = 400
MAX_AI_TIMELINE_CHARS = 120


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


def save_diff(path: str, before: str | None, after: str) -> str:
    """One save's diff, kept on its ``file_saved`` event for the replay;
    cut when huge (the final diff is always whole)."""
    diff = file_diff(path, before, after)
    if len(diff) > MAX_SAVE_DIFF_CHARS:
        return diff[:MAX_SAVE_DIFF_CHARS] + "… (diff cut)\n"
    return diff


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
    if event.kind is MockEventKind.STAGE_UNLOCKED:
        how = "early, at the candidate's request" if d.get("early") else "on schedule"
        return f"the change request (stage {d.get('stage')}) arrived {how}"
    if event.kind is MockEventKind.ASSISTANT_PROMPT:
        text = _one_line(str(d.get("text", "")), MAX_AI_TIMELINE_CHARS)
        return f'asked the AI assistant ({d.get("mode")} mode): "{text}"'
    if event.kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
        path = d.get("path")
        if d.get("decision") == "accepted":
            return f"accepted the AI assistant's edit to {path}"
        if d.get("decision") == "rejected":
            return f"rejected the AI assistant's edit to {path}"
        return f"tried to accept the AI assistant's edit to {path}, but the file had changed"
    if event.kind is MockEventKind.SERVER_ACTION:
        verb = {"start": "started", "stop": "stopped", "restart": "restarted"}
        return f"{verb.get(d.get('action', ''), d.get('action'))} the {d.get('server')} dev server"
    if event.kind is MockEventKind.PREVIEW_RELOADED:
        return f"reloaded the {d.get('server')} preview"
    if event.kind is MockEventKind.SESSION_STARTED:
        return "session started"
    return "session ended"


def _one_line(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


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
        if event.kind in CHAT_KINDS or event.kind in AI_DETAIL_KINDS:
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


def _seconds(ms: object) -> str:
    return f"{int(ms) / 1000:.1f}s" if isinstance(ms, int | float) else "?"


def ai_log(events: list[MockEvent], start: datetime | None) -> str:
    """How the candidate used the AI assistant, turn by turn: the prompt and
    mode, how long the reply took, what the assistant looked at, a cut of its
    reply, and each proposed edit with what the candidate did about it and
    how long they took to decide. Empty if the assistant was never used."""
    prompts = [e for e in events if e.kind is MockEventKind.ASSISTANT_PROMPT]
    if not prompts:
        return ""
    responses = {
        e.data.get("turn"): e for e in events if e.kind is MockEventKind.ASSISTANT_RESPONSE
    }
    decisions: dict[object, list[MockEvent]] = {}
    for e in events:
        if e.kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
            decisions.setdefault(e.data.get("proposalId"), []).append(e)
    proposals: dict[object, list[MockEvent]] = {}
    for e in events:
        if e.kind is MockEventKind.ASSISTANT_EDIT_PROPOSED:
            proposals.setdefault(e.data.get("turn"), []).append(e)

    modes = {m: sum(p.data.get("mode") == m for p in prompts) for m in ("ask", "plan", "edit")}
    outcomes = {"accepted": 0, "rejected": 0, "conflict": 0, "never reviewed": 0}
    blocks: list[list[str]] = []
    for prompt in prompts:
        turn = prompt.data.get("turn")
        response = responses.get(turn)
        r = response.data if response else {}
        status = r.get("status", "interrupted")
        head = f"[{_clock(prompt.at, start)}] {prompt.data.get('mode')} mode"
        head += f", reply in {_seconds(r.get('durationMs'))}"
        if status != "done":
            head += f" ({status}{': ' + str(r['error']) if r.get('error') else ''})"
        text = _one_line(str(prompt.data.get("text", "")), MAX_AI_PROMPT_CHARS)
        block = [head, f"  Prompt: {text}"]
        tools = [str(t) for t in r.get("tools", [])]
        if tools:
            block.append(f"  Looked at: {_one_line('; '.join(tools), MAX_AI_PROMPT_CHARS)}")
        if r.get("text"):
            block.append(f"  Reply: {_one_line(str(r['text']), MAX_AI_REPLY_CHARS)}")
        for p in proposals.get(turn, []):
            d = p.data
            decided = decisions.get(d.get("proposalId"), [])
            kinds = [x.data.get("decision") for x in decided]
            if "accepted" in kinds:
                outcome = "accepted"
            else:
                outcome = str(kinds[-1]) if kinds else "never reviewed"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            final = next((x for x in decided if x.data.get("decision") == outcome), None)
            after = f" after {_seconds(final.data.get('reviewMs'))}" if final else ""
            label = "new file" if d.get("newFile") else "edit to"
            block.append(
                f"  Proposed {label} {d.get('path')} (+{d.get('added', 0)} -{d.get('removed', 0)})"
                f": {_one_line(str(d.get('summary', '')), 160)} -> {outcome}{after}"
            )
        blocks.append(block)

    lines = [line for block in blocks[-MAX_AI_TURNS_SHOWN:] for line in block]
    if len(blocks) > MAX_AI_TURNS_SHOWN:
        lines.insert(0, f"… {len(blocks) - MAX_AI_TURNS_SHOWN} earlier turns cut …")
    proposed = sum(outcomes.values())
    summary = (
        f"{len(prompts)} prompts (ask {modes['ask']}, plan {modes['plan']}, "
        f"edit {modes['edit']}); {proposed} edits proposed: {outcomes['accepted']} accepted, "
        f"{outcomes['rejected']} rejected, {outcomes['conflict']} conflicted with the "
        f"candidate's own changes, {outcomes['never reviewed']} never reviewed."
    )
    return summary + "\n\n" + "\n".join(lines)


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
    ]
    assistant = ai_log(events, session.started_at)
    if assistant:
        parts += ["## AI assistant use", assistant]
    parts += ["## Diff against the starting repo", session.final_diff.strip() or "(no changes)"]
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Replay: every event of the round, for the session page
# --------------------------------------------------------------------------- #

ReplayGroup = Literal["edits", "tests", "app", "assistant", "chat", "stages"]
Tone = Literal["neutral", "good", "bad", "warn", "accent"]
MAX_REPLAY_TEXT_CHARS = 4000

_GROUPS: dict[MockEventKind, ReplayGroup] = {
    MockEventKind.SESSION_STARTED: "stages",
    MockEventKind.SESSION_ENDED: "stages",
    MockEventKind.STAGE_PASSED: "stages",
    MockEventKind.STAGE_SKIPPED: "stages",
    MockEventKind.STAGE_UNLOCKED: "stages",
    MockEventKind.FILE_SAVED: "edits",
    MockEventKind.TESTS_RUN: "tests",
    MockEventKind.STAGE_TESTS_RUN: "tests",
    MockEventKind.COMMAND_RUN: "tests",
    MockEventKind.SERVER_ACTION: "app",
    MockEventKind.PREVIEW_RELOADED: "app",
    MockEventKind.ASSISTANT_PROMPT: "assistant",
    MockEventKind.ASSISTANT_RESPONSE: "assistant",
    MockEventKind.ASSISTANT_EDIT_PROPOSED: "assistant",
    MockEventKind.ASSISTANT_EDIT_DECIDED: "assistant",
    MockEventKind.INTERVIEWER_MESSAGE: "chat",
    MockEventKind.CANDIDATE_MESSAGE: "chat",
}


@dataclass(frozen=True, slots=True)
class ReplayEntry:
    """One moment of the round. ``t`` is seconds from the start (``None``
    when unknown); ``group`` is what the replay filters by."""

    at: datetime | None
    t: float | None
    group: ReplayGroup
    kind: MockEventKind
    title: str
    detail: str = ""
    diff: str = ""
    tone: Tone = "neutral"
    stage: int | None = None
    # Small facts the page shows as chips: mode, decision, review time.
    meta: dict[str, Any] = field(default_factory=dict)


def _cut(text: object, limit: int = MAX_REPLAY_TEXT_CHARS) -> str:
    flat = str(text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _run_tone(status: object) -> Tone:
    return "good" if status == "passed" else "bad"


def _counts(d: dict[str, Any]) -> str:
    failing = int(d.get("failed", 0) or 0) + int(d.get("errors", 0) or 0)
    return f"{d.get('passed', 0)} passed, {failing} failing"


@dataclass(frozen=True, slots=True)
class _Shown:
    title: str
    detail: str = ""
    diff: str = ""
    tone: Tone = "neutral"
    meta: dict[str, Any] = field(default_factory=dict)


_DECISIONS: dict[str, tuple[str, Tone]] = {
    "accepted": ("Accepted", "good"),
    "rejected": ("Rejected", "neutral"),
    "conflict": ("Could not apply (the file had changed)", "warn"),
}
_SERVER_VERBS = {"start": "Started", "stop": "Stopped", "restart": "Restarted"}


def _shown(event: MockEvent, decisions: dict[object, MockEvent]) -> _Shown:
    d = event.data
    kind = event.kind
    if kind is MockEventKind.FILE_SAVED:
        lines = {"added": d.get("added", 0), "removed": d.get("removed", 0)}
        return _Shown(f"Saved {d.get('path')}", diff=str(d.get("diff") or ""), meta=lines)
    if kind is MockEventKind.TESTS_RUN:
        return _Shown(f"Ran tests: {_counts(d)}", tone=_run_tone(d.get("status")))
    if kind is MockEventKind.STAGE_TESTS_RUN:
        title = f"Ran stage {d.get('stage')}'s hidden tests: {_counts(d)}"
        return _Shown(title, tone=_run_tone(d.get("status")))
    if kind is MockEventKind.COMMAND_RUN:
        tone: Tone = "bad" if d.get("exitCode") else "neutral"
        return _Shown(f"$ {d.get('command')}", tone=tone, meta={"exitCode": d.get("exitCode")})
    if kind is MockEventKind.SERVER_ACTION:
        verb = _SERVER_VERBS.get(str(d.get("action")), str(d.get("action")))
        return _Shown(f"{verb} the {d.get('server')} server")
    if kind is MockEventKind.PREVIEW_RELOADED:
        return _Shown(f"Reloaded the {d.get('server')} preview")
    if kind is MockEventKind.ASSISTANT_PROMPT:
        mode = d.get("mode")
        return _Shown("Asked the AI", _cut(d.get("text")), tone="accent", meta={"mode": mode})
    if kind is MockEventKind.ASSISTANT_RESPONSE:
        status = str(d.get("status") or "done")
        done = status == "done"
        title = f"AI replied in {_seconds(d.get('durationMs'))}" if done else f"AI reply {status}"
        meta = {"mode": d.get("mode"), "tools": len(d.get("tools") or [])}
        return _Shown(title, _cut(d.get("text")), tone="neutral" if done else "warn", meta=meta)
    if kind is MockEventKind.ASSISTANT_EDIT_PROPOSED:
        decided = decisions.get(d.get("proposalId"))
        label = "a new file" if d.get("newFile") else "an edit to"
        meta = {
            "outcome": str(decided.data.get("decision")) if decided else "never reviewed",
            "added": d.get("added", 0),
            "removed": d.get("removed", 0),
        }
        return _Shown(
            f"AI proposed {label} {d.get('path')}",
            _cut(d.get("summary"), 400),
            str(d.get("diff") or ""),
            "accent",
            meta,
        )
    if kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
        decision = str(d.get("decision"))
        verb, decided_tone = _DECISIONS.get(decision, (decision, "neutral"))
        title = f"{verb} the AI's edit to {d.get('path')}"
        if decision != "conflict":
            title += f" after {_seconds(d.get('reviewMs'))}"
        meta = {"decision": decision, "reviewMs": d.get("reviewMs")}
        return _Shown(title, tone=decided_tone, meta=meta)
    if kind is MockEventKind.INTERVIEWER_MESSAGE:
        return _Shown("Interviewer", _cut(d.get("text")), meta={"trigger": d.get("trigger")})
    if kind is MockEventKind.CANDIDATE_MESSAGE:
        return _Shown("You", _cut(d.get("text")))
    if kind is MockEventKind.STAGE_UNLOCKED:
        early = bool(d.get("early"))
        title = f"Change request arrived (stage {d.get('stage')})"
        return _Shown(
            title + (", early at your request" if early else ""), tone="warn", meta={"early": early}
        )
    if kind is MockEventKind.STAGE_PASSED:
        return _Shown(f"Passed stage {d.get('stage')}", tone="good")
    if kind is MockEventKind.STAGE_SKIPPED:
        return _Shown(f"Skipped stage {d.get('stage')}", tone="warn")
    if kind is MockEventKind.SESSION_STARTED:
        return _Shown("Round started")
    return _Shown(
        "Round ended" + (" (the sandbox was already gone)" if d.get("sandboxLost") else "")
    )


def replay(events: list[MockEvent], start: datetime | None) -> list[ReplayEntry]:
    """Every event of a live session in order, as the session page shows
    it: saves with their diffs, test runs, dev-server actions, the AI
    assistant (prompts by mode, replies, proposed edits with what became of
    them and the review time), the interviewer chat, and stage changes
    including the change request's arrival."""
    decisions: dict[object, MockEvent] = {}
    for e in events:
        if e.kind is MockEventKind.ASSISTANT_EDIT_DECIDED:
            # An accept that conflicted can be retried; the last word counts.
            decisions[e.data.get("proposalId")] = e
    entries = []
    for event in events:
        group = _GROUPS.get(event.kind)
        if group is None:
            continue
        shown = _shown(event, decisions)
        t = (event.at - start).total_seconds() if event.at and start else None
        stage = event.data.get("stage")
        entries.append(
            ReplayEntry(
                at=event.at,
                t=max(0.0, t) if t is not None else None,
                group=group,
                kind=event.kind,
                title=shown.title,
                detail=shown.detail,
                diff=shown.diff,
                tone=shown.tone,
                stage=stage if isinstance(stage, int) else None,
                meta=shown.meta,
            )
        )
    return entries
