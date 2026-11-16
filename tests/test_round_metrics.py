"""The numbers an AI-assisted round is analysed on, and the replay of a
round, from a recorded generated round (``tests/round_fixture.py``)."""

from __future__ import annotations

from datetime import timedelta

from dayline.api.serializers import replay_json
from dayline.mock import round_metrics
from dayline.mock.worklog import replay
from dayline.models import MockEventKind, StageStatus
from tests.round_fixture import DTO, SERVICE, T0, recorded_round


def _metrics() -> round_metrics.RoundMetrics:
    problem, session, events = recorded_round()
    assert session.started_at and session.ended_at
    return round_metrics.compute(
        problem, session.stages, events, session.started_at, session.ended_at
    )


def test_orientation_prompting_and_planning() -> None:
    m = _metrics()
    assert m.duration_s == 44 * 60
    assert m.first_save_s == 5 * 60 + 44
    assert (m.prompts_before_first_save, m.checks_before_first_save) == (3, 0)
    assert m.prompts == {"ask": 1, "plan": 1, "edit": 2}
    assert m.median_prompt_words == 14  # 14, 15, 14 and 4 words
    # Only the ask and the task's edit name a file or an identifier.
    assert m.scoped_prompts == 2
    # The task's edit followed a plan; the change request's did not.
    assert m.edit_prompts_after_plan == 1


def test_diff_review_and_verification() -> None:
    m = _metrics()
    assert (m.proposed, m.accepted, m.rejected, m.conflicted, m.never_reviewed) == (3, 3, 0, 0, 0)
    assert m.quick_accepts == 2 and m.median_accept_review_s == 4.0
    # 05:44 was followed by another accept (06:30) before any check; 06:30 by
    # the 07:10 test run; 28:02 by the 33:00 hidden run.
    assert m.verified_accepts == 2
    assert (m.test_runs, m.hidden_runs, m.preview_reloads) == (1, 3, 1)
    assert m.runs_after_last_save == 1


def test_change_request_time_and_final_correctness() -> None:
    m = _metrics()
    assert m.change_request_s == 25 * 60 and not m.change_request_early
    assert m.first_action_after_cr_s == 100
    assert m.first_action_after_cr == "spoke to the interviewer"
    assert m.first_save_after_cr_s == 3 * 60 + 2
    assert m.first_prompt_after_cr_mode == "edit" and m.questions_after_cr == 1
    # Idle from the 10:00 preview reload to the 26:40 question.
    assert m.longest_gap_s == 16 * 60 + 40 and m.longest_gap_at_s == 10 * 60
    assert [(s.number, s.status, s.tests_passed, s.tests_total) for s in m.stages] == [
        (1, StageStatus.PASSED, 2, 2),
        (2, StageStatus.PASSED, 2, 2),
    ]
    assert m.stages[0].time_spent_s == 9 * 60 + 30


def test_metrics_text_is_citable() -> None:
    text = round_metrics.metrics_text(_metrics())
    lines = text.splitlines()
    assert lines[0].startswith("## Round metrics")
    assert "first save at 05:44" in text
    assert "Accepted edits reviewed under 10s: 2/3 (67%)" in text
    assert "Change request: arrived at 25:00 (on schedule); first action 1m 40s later" in text
    assert "longest stretch without activity 16m 40s from 10:00" in text
    assert "first AI prompt after it in edit mode; 1 question to the interviewer" in text
    assert "1 visible test run, 3 hidden test runs, 1 preview reload; 1 test run after" in text
    assert "- Stage 2 (Filter by tag) final: passed; its hidden tests in the last run: 2/2" in text


def test_the_analysis_record_has_stages_metrics_and_the_timeline() -> None:
    problem, session, events = recorded_round()
    assert session.ended_at
    record = round_metrics.analysis_record(problem, session, events, session.ended_at)
    stages_at, metrics_at, timeline_at = (
        record.index("## Staged round"),
        record.index("## Round metrics"),
        record.index("## Timeline"),
    )
    assert stages_at < metrics_at < timeline_at
    assert "(the change request; arrived at 25:00, scheduled 25:00)" in record
    assert "25:00 the change request (stage 2) arrived on schedule" in record
    assert "## AI assistant use" in record


def test_a_round_without_a_change_request_or_assistant_still_measures() -> None:
    _, _, events = recorded_round()
    kinds = (MockEventKind.SESSION_STARTED, MockEventKind.FILE_SAVED)
    plain = [e for e in events if e.kind in kinds]
    m = round_metrics.compute(None, [], plain, T0, T0 + timedelta(minutes=10))
    assert m.change_request_s is None and m.accepted == 0 and m.stages == []
    text = round_metrics.metrics_text(m)
    assert "Change request" not in text and "0/0" in text


def test_the_replay_shows_every_moment_with_its_detail() -> None:
    _, session, events = recorded_round()
    entries = replay(events, session.started_at)
    assert len(entries) == len(events)
    by_kind = {e.kind: e for e in entries}
    saved = next(e for e in entries if e.kind is MockEventKind.FILE_SAVED and DTO in e.title)
    assert saved.group == "edits" and "+title: string; tags?: string[];" in saved.diff
    assert saved.meta == {"added": 4, "removed": 0} and saved.t == 6 * 60 + 30
    proposed = [e for e in entries if e.kind is MockEventKind.ASSISTANT_EDIT_PROPOSED]
    assert proposed[0].title == f"AI proposed an edit to {SERVICE}"
    assert proposed[0].meta["outcome"] == "accepted" and proposed[0].diff
    decided = next(e for e in entries if e.kind is MockEventKind.ASSISTANT_EDIT_DECIDED)
    assert decided.title == f"Accepted the AI's edit to {SERVICE} after 4.0s"
    assert decided.tone == "good" and decided.meta["reviewMs"] == 4000
    prompt = by_kind[MockEventKind.ASSISTANT_PROMPT]
    assert prompt.group == "assistant" and prompt.meta == {"mode": "edit"}
    unlocked = by_kind[MockEventKind.STAGE_UNLOCKED]
    assert unlocked.title == "Change request arrived (stage 2)" and unlocked.t == 25 * 60
    assert by_kind[MockEventKind.CANDIDATE_MESSAGE].detail.startswith("Should an unknown tag")
    assert by_kind[MockEventKind.PREVIEW_RELOADED].group == "app"
    groups = {e.group for e in entries}
    assert groups == {"edits", "tests", "app", "assistant", "chat", "stages"}


def test_replay_json_carries_the_scrubber_bounds() -> None:
    _, session, events = recorded_round()
    data = replay_json(session, replay(events, session.started_at), T0)
    assert data["durationS"] == 44 * 60 and data["changeRequestS"] == 25 * 60
    first = data["entries"][0]
    assert first == {
        "t": 0.0,
        "at": T0.isoformat(),
        "group": "stages",
        "kind": "session_started",
        "title": "Round started",
        "detail": "",
        "diff": "",
        "tone": "neutral",
        "stage": None,
        "meta": {},
    }
