"""Staged-round rules with no I/O: content loading, which hidden tests a run
includes, stage transitions, scoring, and the chat transcript. Real test runs
are in test_staged_lru.py; the API in test_mock_staged_api.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from dayline.adapters.sandbox import RunnerSandboxClient, SandboxRequestError
from dayline.mock import staged
from dayline.mock.worklog import chat_transcript, timeline
from dayline.models import MockEvent, MockEventKind, StageStatus

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
LRU = staged.builtin_staged_problems()["lru-cache"]


def _case(stage: int, name: str, outcome: str) -> dict[str, Any]:
    return {"classname": LRU.stages[stage - 1].test_module, "name": name, "outcome": outcome}


def _report(*cases: dict[str, Any]) -> dict[str, Any]:
    failing = any(c["outcome"] != "passed" for c in cases)
    return {"status": "failed" if failing else "passed", "cases": list(cases)}


def _passing(stage: int) -> list[dict[str, Any]]:
    return [_case(stage, name, "passed") for name in LRU.stages[stage - 1].test_names]


def test_stage_test_modules_are_unique_and_match_their_folder() -> None:
    modules = [s.test_module for s in LRU.stages]
    assert modules == [
        "test_stage_1_base",
        "test_stage_2_ttl",
        "test_stage_3_weighted",
        "test_stage_4_concurrency",
    ]


def test_a_problem_with_a_bad_edge_case_does_not_load(tmp_path: Path) -> None:
    source = staged.PROBLEMS_DIR / "lru-cache"
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            target = tmp_path / "broken" / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path.read_text())
    stage_toml = tmp_path / "broken" / "stages" / "1-base" / "stage.toml"
    text = stage_toml.read_text()
    stage_toml.write_text(text.replace("test_falsy_values_are_cached", "test_nope"))
    with pytest.raises(ValueError, match="unknown tests"):
        staged._load(tmp_path / "broken")


def test_a_run_includes_active_and_passed_stages_but_not_skipped_ones() -> None:
    stages = staged.new_round(LRU, T0)
    assert list(staged.hidden_files(LRU, stages)) == ["test_stage_1_base.py"]
    staged.finish_stage(LRU, stages, 0, StageStatus.PASSED, {}, T0)
    staged.finish_stage(LRU, stages, 1, StageStatus.SKIPPED, {}, T0)
    assert list(staged.hidden_files(LRU, stages)) == [
        "test_stage_1_base.py",
        "test_stage_3_weighted.py",
    ]


def test_a_stage_passes_only_when_all_its_own_tests_ran_and_passed() -> None:
    stage = LRU.stages[0]
    assert staged.run_passes(LRU, stage, _report(*_passing(1)))
    # A green run that never collected one of the stage's tests does not count.
    assert not staged.run_passes(LRU, stage, _report(*_passing(1)[1:]))
    # Nor does one where an earlier (here: a later-numbered) stage's test failed.
    assert not staged.run_passes(LRU, stage, _report(*_passing(1), _case(2, "test_x", "failed")))


def test_a_parametrized_test_takes_its_worst_outcome() -> None:
    report = _report(
        _case(1, "test_capacity_below_one_is_rejected[0]", "passed"),
        _case(1, "test_capacity_below_one_is_rejected[-1]", "failed"),
        _case(1, "test_capacity_one", "passed"),
    )
    assert staged.stage_outcomes(LRU, LRU.stages[0], report) == {
        "test_capacity_below_one_is_rejected": "failed",
        "test_capacity_one": "passed",
    }


def test_transitions_unlock_the_next_stage_and_the_end_fails_the_active_one() -> None:
    stages = staged.new_round(LRU, T0)
    assert [s.status for s in stages] == [StageStatus.ACTIVE] + [StageStatus.LOCKED] * 3
    later = T0 + timedelta(minutes=10)
    staged.finish_stage(LRU, stages, 0, StageStatus.PASSED, {"lru_cache.py": "v1"}, later)
    assert (stages[0].finished_at, stages[1].status, stages[1].started_at) == (
        later,
        StageStatus.ACTIVE,
        later,
    )
    with pytest.raises(ValueError):
        staged.finish_stage(LRU, stages, 1, StageStatus.FAILED, {}, later)
    with pytest.raises(ValueError):
        staged.finish_stage(LRU, stages, 0, StageStatus.PASSED, {}, later)
    staged.close_round(stages, {"lru_cache.py": "v2"}, later)
    assert (stages[1].status, stages[1].code) == (StageStatus.FAILED, {"lru_cache.py": "v2"})
    assert staged.active_index(stages) is None
    with pytest.raises(ValueError):
        staged.record_run(LRU, stages, _report())


def test_the_first_run_decides_which_edge_cases_were_handled_up_front() -> None:
    stages = staged.new_round(LRU, T0)
    first = _report(
        *[c for c in _passing(1) if c["name"] != "test_falsy_values_are_cached"],
        _case(1, "test_falsy_values_are_cached", "failed"),
    )
    assert staged.record_run(LRU, stages, first) == []
    edges = {e.id: e.outcome for e in staged.score_round(LRU, stages, T0)[0].edge_cases}
    assert edges == {"update_existing_key": "hit", "falsy_values": "pending"}

    assert staged.record_run(LRU, stages, _report(*_passing(1))) == [0]
    edges = {e.id: e.outcome for e in staged.score_round(LRU, stages, T0)[0].edge_cases}
    assert edges == {"update_existing_key": "hit", "falsy_values": "caught"}
    assert stages[0].runs == 2


def test_stages_never_reached_are_scored_as_such() -> None:
    stages = staged.new_round(LRU, T0)
    staged.close_round(stages, {}, T0 + timedelta(minutes=5))
    results = staged.score_round(LRU, stages, T0 + timedelta(hours=1))
    assert results[0].status is StageStatus.FAILED and results[0].time_spent_s == 300
    assert {e.outcome for e in results[0].edge_cases} == {"missed"}
    assert results[3].time_spent_s is None
    assert {e.outcome for e in results[3].edge_cases} == {"not_reached"}


def test_design_change_ignores_whitespace_and_comments() -> None:
    before = {"a.py": "x = 1\n\n# note\ny = 2\n"}
    after = {"a.py": "x  =  1\ny = 2\n# changed note\nz = 3\n"}
    change = staged.design_change(before, after)
    assert change is not None and change.kept == 1.0 and change.verdict == "extended"
    assert staged.design_change({}, after) is None
    # Unchanged code (a stage skipped untouched) is not a design change at all.
    assert staged.design_change(before, {"a.py": "x = 1\ny = 2\n"}) is None


def test_round_record_reads_like_a_scorecard_input() -> None:
    stages = staged.new_round(LRU, T0)
    staged.record_run(LRU, stages, _report(*_passing(1)))
    staged.finish_stage(LRU, stages, 0, StageStatus.PASSED, {}, T0 + timedelta(seconds=754))
    record = staged.round_record(LRU, stages, T0 + timedelta(minutes=20))
    lines = record.splitlines()
    head = "Stage 1 (Base LRU cache): passed after 12:34 (target 15 min), 1 hidden test run"
    assert head in lines
    edge = LRU.stages[0].edge_cases[0].title
    assert f"- {edge}: handled up front" in lines
    assert "Stage 3 (Weighted size): locked, 0 hidden test runs" in lines


def test_the_chat_is_a_transcript_and_stays_out_of_the_timeline() -> None:
    events = [
        MockEvent("s", MockEventKind.SESSION_STARTED, {}, at=T0),
        MockEvent("s", MockEventKind.INTERVIEWER_MESSAGE, {"stage": 1, "text": "Hi"}, at=T0),
        MockEvent(
            "s", MockEventKind.CANDIDATE_MESSAGE, {"stage": 1, "text": "Hello"},
            at=T0 + timedelta(seconds=65),
        ),
        MockEvent(
            "s", MockEventKind.STAGE_TESTS_RUN,
            {"stage": 1, "status": "passed", "passed": 11, "failed": 0, "errors": 0},
            at=T0 + timedelta(seconds=90),
        ),
        MockEvent("s", MockEventKind.STAGE_SKIPPED, {"stage": 2}, at=T0 + timedelta(seconds=95)),
    ]  # fmt: skip
    assert chat_transcript(events, T0) == "[00:00] Interviewer: Hi\n[01:05] Candidate: Hello"
    assert timeline(events, T0) == [
        "00:00 session started",
        "01:30 ran stage 1's hidden tests: passed (11 passed, 0 failed, 0 errors)",
        "01:35 skipped stage 2 without passing it",
    ]


def test_an_old_runner_without_hidden_tests_says_so() -> None:
    client = RunnerSandboxClient("http://runner", "s" * 40)
    client._http = httpx.Client(
        base_url="http://runner",
        transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"detail": "Not Found"})),
    )
    with pytest.raises(SandboxRequestError) as caught:
        client.run_hidden_tests("abc", {"test_x.py": ""})
    assert caught.value.status_code == 501 and "redeploy" in caught.value.detail
