"""Timed stages: a generated round's change request arrives at its minute,
whatever stage 1's state; passing stage 1 early keeps the candidate on it
until then (or until they ask for the change request); an unpassed stage 1
keeps counting after it arrives; and built-in rounds are untouched."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from dayline.adapters.mock_source import _json_to_stage, _stage_to_json
from dayline.mock import staged
from dayline.models import StageStatus
from tests.round_fixture import PROBLEM, T0

CR = T0 + timedelta(minutes=25)


def _report(passing: set[int], stages: tuple[int, ...] = (1, 2)) -> dict[str, Any]:
    cases = [
        {
            "classname": f"stage{n}",
            "name": f"case {n}{x}",
            "outcome": "passed" if n in passing else "failed",
        }
        for n in stages
        for x in "ab"
    ]
    failed = sum(c["outcome"] != "passed" for c in cases)
    return {"status": "failed" if failed else "passed", "cases": cases}


def _statuses(stages: list[Any]) -> list[StageStatus]:
    return [s.status for s in stages]


def test_only_generated_stages_after_the_first_are_timed() -> None:
    assert PROBLEM.timed and [s.timed for s in PROBLEM.stages] == [False, True]
    lru = staged.builtin_staged_problems()["lru-cache"]
    assert not lru.timed


def test_the_change_request_arrives_at_its_minute_even_if_stage_1_has_not_passed() -> None:
    stages = staged.new_round(PROBLEM, T0)
    assert staged.next_unlock(PROBLEM, stages, T0) == (1, CR)
    assert staged.unlock_due(PROBLEM, stages, T0, CR - timedelta(seconds=1)) == []
    # Noticed late (nobody asked until 31:00): stamped with its own minute.
    assert staged.unlock_due(PROBLEM, stages, T0, CR + timedelta(minutes=6)) == [1]
    assert _statuses(stages) == [StageStatus.ACTIVE, StageStatus.ACTIVE]
    assert stages[1].started_at == CR
    assert staged.focus_index(stages) == 1 and staged.active_index(stages) == 1
    assert staged.next_unlock(PROBLEM, stages, T0) is None
    # Unlocking is idempotent: a second read changes nothing.
    assert staged.unlock_due(PROBLEM, stages, T0, CR + timedelta(minutes=7)) == []
    # Both stages' tests run from now on.
    assert len(staged.hidden_files(PROBLEM, stages)) == 2


def test_stage_1_keeps_counting_after_the_change_request() -> None:
    stages = staged.new_round(PROBLEM, T0)
    staged.unlock_due(PROBLEM, stages, T0, CR)
    # Stage 1 finally passes while stage 2 still fails: stage 1 is done.
    assert staged.record_run(PROBLEM, stages, _report({1})) == [0]
    staged.finish_stage(PROBLEM, stages, 0, StageStatus.PASSED, {}, CR + timedelta(minutes=3))
    assert _statuses(stages) == [StageStatus.PASSED, StageStatus.ACTIVE]
    assert stages[0].runs == 1 and stages[1].runs == 1
    # Stage 2 passes only with stage 1 still passing.
    assert staged.record_run(PROBLEM, stages, _report({2})) == []
    assert staged.record_run(PROBLEM, stages, _report({1, 2})) == [1]


def test_both_stages_can_pass_in_one_run() -> None:
    stages = staged.new_round(PROBLEM, T0)
    staged.unlock_due(PROBLEM, stages, T0, CR)
    assert staged.record_run(PROBLEM, stages, _report({1, 2})) == [0, 1]


def test_passing_stage_1_early_keeps_the_candidate_on_it_until_the_minute() -> None:
    stages = staged.new_round(PROBLEM, T0)
    early = T0 + timedelta(minutes=12)
    assert staged.record_run(PROBLEM, stages, _report({1}, (1,))) == [0]
    staged.finish_stage(PROBLEM, stages, 0, StageStatus.PASSED, {"a": "v1"}, early)
    assert _statuses(stages) == [StageStatus.PASSED, StageStatus.LOCKED]
    # Still in stage 1, polishing: runs still count there and nothing is active.
    assert staged.focus_index(stages) == 0 and staged.active_index(stages) is None
    assert staged.record_run(PROBLEM, stages, _report(set(), (1,))) == []
    assert stages[0].runs == 2 and stages[0].status is StageStatus.PASSED
    assert staged.unlock_due(PROBLEM, stages, T0, CR) == [1]
    assert stages[1].started_at == CR


def test_done_early_brings_the_change_request_now() -> None:
    stages = staged.new_round(PROBLEM, T0)
    assert not staged.can_bring_early(PROBLEM, stages)  # Stage 1 is still active.
    with pytest.raises(ValueError):
        staged.bring_early(PROBLEM, stages, T0)
    staged.finish_stage(PROBLEM, stages, 0, StageStatus.PASSED, {}, T0 + timedelta(minutes=12))
    assert staged.can_bring_early(PROBLEM, stages)
    now = T0 + timedelta(minutes=14)
    assert staged.bring_early(PROBLEM, stages, now) == 1
    assert stages[1].status is StageStatus.ACTIVE and stages[1].started_at == now
    assert not staged.can_bring_early(PROBLEM, stages)
    # Its minute passing later changes nothing.
    assert staged.unlock_due(PROBLEM, stages, T0, CR) == []


def test_skipping_stage_1_brings_the_change_request_at_once() -> None:
    stages = staged.new_round(PROBLEM, T0)
    now = T0 + timedelta(minutes=8)
    staged.finish_stage(PROBLEM, stages, 0, StageStatus.SKIPPED, {}, now)
    assert _statuses(stages) == [StageStatus.SKIPPED, StageStatus.ACTIVE]
    assert stages[1].started_at == now
    # A skipped stage's tests stay out of the run.
    assert list(staged.hidden_files(PROBLEM, stages)) == ["stage2.test.ts"]


def test_the_end_fails_every_stage_still_active_and_closes_the_round() -> None:
    stages = staged.new_round(PROBLEM, T0)
    staged.unlock_due(PROBLEM, stages, T0, CR)
    staged.close_round(stages, {"a": "final"}, T0 + timedelta(minutes=45))
    assert _statuses(stages) == [StageStatus.FAILED, StageStatus.FAILED]
    assert staged.focus_index(stages) is None
    with pytest.raises(ValueError):
        staged.record_run(PROBLEM, stages, _report({1, 2}))


def test_a_round_reloaded_mid_way_keeps_its_schedule() -> None:
    """The schedule lives in what is stored (the stages and the round's
    start), so a reload - a fresh read from the database - unlocks the change
    request at the same minute."""
    stages = staged.new_round(PROBLEM, T0)
    staged.finish_stage(PROBLEM, stages, 0, StageStatus.PASSED, {}, T0 + timedelta(minutes=9))
    reloaded = [_json_to_stage(_stage_to_json(s)) for s in stages]
    assert reloaded == stages
    assert staged.next_unlock(PROBLEM, reloaded, T0) == (1, CR)
    assert staged.unlock_due(PROBLEM, reloaded, T0, CR + timedelta(seconds=30)) == [1]
    assert reloaded[1].started_at == CR


def test_round_record_names_when_the_change_request_arrived() -> None:
    stages = staged.new_round(PROBLEM, T0)
    staged.finish_stage(PROBLEM, stages, 0, StageStatus.PASSED, {}, T0 + timedelta(minutes=12))
    staged.bring_early(PROBLEM, stages, T0 + timedelta(minutes=20, seconds=5))
    record = staged.round_record(PROBLEM, stages, T0 + timedelta(minutes=30))
    assert "(the change request; arrived at 20:05, scheduled 25:00)" in record
