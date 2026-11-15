"""The LRU staged problem's content: every reference solution passes its
stage and all earlier ones, and solutions with one classic mistake fail
exactly the stage (and edge case) that mistake belongs to.

The hidden tests run in a local subprocess the way the sandbox runner runs
them (``tests/staged_harness.py``), so this needs no Docker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from dayline.mock import staged
from dayline.mock.staged import StagedProblem
from dayline.models import StageAttempt, StageStatus
from tests.staged_harness import run_hidden

SOLUTION = "lru_cache.py"


@pytest.fixture(scope="module")
def lru() -> StagedProblem:
    return staged.builtin_staged_problems()["lru-cache"]


def _attempts(problem: StagedProblem, active: int) -> list[StageAttempt]:
    """Stages 1..active-1 passed, stage ``active`` active."""
    return [
        StageAttempt(
            status=StageStatus.PASSED
            if n < active
            else StageStatus.ACTIVE
            if n == active
            else StageStatus.LOCKED
        )
        for n in range(1, len(problem.stages) + 1)
    ]


def _run(problem: StagedProblem, code: str, stage: int) -> dict[str, Any]:
    """Run stage ``stage``'s hidden tests (plus every earlier stage's) on ``code``."""
    return run_hidden({SOLUTION: code}, staged.hidden_files(problem, _attempts(problem, stage)))


def _failing(problem: StagedProblem, report: dict[str, Any]) -> dict[int, set[str]]:
    """{stage number: failing test names}."""
    failing: dict[int, set[str]] = {}
    for stage in problem.stages:
        names = {
            name
            for name, outcome in staged.stage_outcomes(problem, stage, report).items()
            if outcome != "passed"
        }
        if names:
            failing[stage.number] = names
    return failing


def _variant(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, f"{old!r} must appear exactly once"
    return source.replace(old, new)


def test_the_problem_loads_with_four_stages_and_its_edge_cases(lru: StagedProblem) -> None:
    assert [s.title for s in lru.stages] == [
        "Base LRU cache",
        "Per-entry TTL",
        "Weighted size",
        "Thread safety",
    ]
    assert lru.solution == (SOLUTION,) and SOLUTION in lru.starter
    edges = {e.id for s in lru.stages for e in s.edge_cases}
    assert {"oversized_item", "expired_but_present", "update_changes_size"} <= edges
    assert sorted(lru.references) == [1, 2, 3, 4]


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_the_reference_passes_its_stage_and_every_earlier_one(
    lru: StagedProblem, stage: int
) -> None:
    report = _run(lru, lru.references[stage], stage)
    assert report["status"] == "passed", report["output"]
    attempts = _attempts(lru, stage)
    assert staged.record_run(lru, attempts, report) is True
    # Every stage's every test actually ran.
    ran = {(c["classname"], c["name"].split("[")[0]) for c in report["cases"]}
    for s in lru.stages[:stage]:
        assert {(s.test_module, name) for name in s.test_names} <= ran


def test_the_starter_fails_stage_1(lru: StagedProblem) -> None:
    report = _run(lru, lru.starter[SOLUTION], 1)
    assert report["status"] == "failed"
    assert _failing(lru, report)[1] == lru.stages[0].test_names


def test_each_reference_breaks_on_the_next_stage(lru: StagedProblem) -> None:
    """Every stage really asks for something new."""
    for stage in (1, 2, 3):
        failing = _failing(lru, _run(lru, lru.references[stage], stage + 1))
        assert set(failing) == {stage + 1}, failing


# (stage, one-bug variant of that stage's reference, the tests it must fail)
MISTAKES = {
    "get_does_not_refresh_recency": (
        1,
        lambda ref: _variant(
            ref,
            "        self._unlink(node)\n        self._push_front(node)\n        return node.value",
            "        return node.value",
        ),
        {"test_get_makes_a_key_most_recently_used", "test_random_operations_match_a_simple_model"},
    ),
    "evicts_before_checking_for_an_update": (
        1,
        lambda ref: _variant(
            ref,
            "        node = self._map.get(key)\n        if node is not None:\n"
            "            self._remove(node)\n        while len(self._map) >= self.capacity:\n"
            "            self._remove(self._tail.prev)\n",
            "        while len(self._map) >= self.capacity:\n"
            "            self._remove(self._tail.prev)\n        node = self._map.get(key)\n"
            "        if node is not None:\n            self._remove(node)\n",
        ),
        {"test_updating_a_key_never_evicts", "test_random_operations_match_a_simple_model"},
    ),
    "returns_expired_entries_still_in_the_map": (
        2,
        lambda ref: _variant(
            ref,
            "        if node.expires_at is not None and self._clock() >= node.expires_at:\n"
            "            self._remove(node)\n            return None\n",
            "",
        ),
        {
            "test_an_entry_expires_when_its_ttl_is_up",
            "test_an_expired_key_can_be_put_again",
            "test_expired_key_is_never_returned_while_still_stored",
            "test_expired_key_stays_gone_after_other_operations",
        },
    ),
    "keeps_the_old_ttl_on_update": (
        2,
        lambda ref: _variant(
            ref,
            "        node = self._map.get(key)\n        if node is not None:\n"
            "            self._remove(node)\n",
            "        node = self._map.get(key)\n        if node is not None:\n"
            "            node.value = value\n            self._unlink(node)\n"
            "            self._push_front(node)\n            return\n",
        ),
        {"test_put_replaces_the_ttl"},
    ),
    "evicts_only_one_entry_per_put": (
        3,
        lambda ref: _variant(
            ref,
            "        while self._total + size > self.capacity:",
            "        if self._total + size > self.capacity:",
        ),
        {"test_one_put_can_evict_several_entries", "test_eviction_by_size_follows_recency"},
    ),
    "has_no_oversized_policy": (
        3,
        lambda ref: _variant(
            ref,
            "        if size > self.capacity:\n"
            '            raise ValueError(f"size {size} is larger than the capacity '
            '{self.capacity}")\n',
            "",
        ),
        {"test_an_oversized_item_leaves_the_cache_intact"},
    ),
    "updates_in_place_without_size_bookkeeping": (
        3,
        lambda ref: _variant(
            ref,
            "        node = self._map.get(key)\n        if node is not None:\n"
            "            self._remove(node)\n",
            "        node = self._map.get(key)\n        if node is not None:\n"
            "            node.value, node.size = value, size\n"
            "            node.expires_at = None if ttl is None else self._clock() + ttl\n"
            "            self._unlink(node)\n            self._push_front(node)\n"
            "            return\n",
        ),
        {"test_growing_a_key_evicts_others_but_never_itself", "test_shrinking_a_key_frees_room"},
    ),
}


@pytest.mark.parametrize("mistake", sorted(MISTAKES))
def test_a_classic_mistake_fails_exactly_its_tests(lru: StagedProblem, mistake: str) -> None:
    stage, make, expected = MISTAKES[mistake]
    report = _run(lru, make(lru.references[stage]), stage)
    assert _failing(lru, report) == {stage: expected}
    assert staged.record_run(lru, _attempts(lru, stage), report) is False


NO_LOCK = "the stage 3 reference: correct, but with no lock at all"

# A real read-write lock with get() on the shared side: the trap stage 4's
# interviewer probes, since get() moves the node and so is a write.
RW_LOCK = '''
import threading


class _ReadWriteLock:
    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0

    def acquire_read(self):
        with self._cond:
            self._readers += 1

    def release_read(self):
        with self._cond:
            self._readers -= 1
            self._cond.notify_all()

    def acquire_write(self):
        self._cond.acquire()
        self._cond.wait_for(lambda: self._readers == 0)

    def release_write(self):
        self._cond.release()
'''


def _rw_locked(stage_3: str) -> str:
    code = _variant(stage_3, "import time\n", f"import time\n{RW_LOCK}")
    code = _variant(
        code,
        "        self._total = 0\n",
        "        self._total = 0\n        self._rw = _ReadWriteLock()\n",
    )
    code = _variant(
        code,
        '        """The cached value for ``key``, or ``None`` if it is not cached."""\n',
        '        """The cached value for ``key``, or ``None`` if it is not cached."""\n'
        "        self._rw.acquire_read()\n        try:\n            return self._get(key)\n"
        "        finally:\n            self._rw.release_read()\n\n    def _get(self, key):\n",
    )
    return _variant(
        code,
        "    def put(self, key, value, ttl=None, size=1) -> None:\n",
        "    def put(self, key, value, ttl=None, size=1) -> None:\n"
        "        self._rw.acquire_write()\n        try:\n"
        "            self._put(key, value, ttl, size)\n        finally:\n"
        "            self._rw.release_write()\n\n"
        "    def _put(self, key, value, ttl=None, size=1):\n",
    )


@pytest.mark.parametrize("variant", ["no_lock", "read_write_lock"])
def test_an_unsafe_cache_fails_stage_4_every_time(lru: StagedProblem, variant: str) -> None:
    code = lru.references[3] if variant == "no_lock" else _rw_locked(lru.references[3])
    for _ in range(3):  # Races are probabilistic; the tests must catch them every run.
        failing = _failing(lru, _run(lru, code, 4))
        assert set(failing) == {4}
        assert "test_concurrent_reads_keep_the_cache_consistent" in failing[4]
        assert "test_single_threaded_behaviour_is_unchanged" not in failing[4]


def test_the_reference_progression_extends_each_design(lru: StagedProblem) -> None:
    for stage in (2, 3, 4):
        change = staged.design_change(
            {SOLUTION: lru.references[stage - 1]}, {SOLUTION: lru.references[stage]}
        )
        assert change is not None and change.verdict == "extended", (stage, change)


ORDERED_DICT_STAGE_1 = '''from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key):
        if key not in self.data:
            return None
        self.data.move_to_end(key)
        return self.data[key]

    def put(self, key, value) -> None:
        if key in self.data:
            self.data.move_to_end(key)
        elif len(self.data) >= self.capacity:
            self.data.popitem(last=False)
        self.data[key] = value
'''


def test_an_ordered_dict_solution_passes_stage_1_and_switching_away_is_a_rewrite(
    lru: StagedProblem,
) -> None:
    assert _run(lru, ORDERED_DICT_STAGE_1, 1)["status"] == "passed"
    change = staged.design_change({SOLUTION: ORDERED_DICT_STAGE_1}, {SOLUTION: lru.references[2]})
    assert change is not None and change.verdict == "rewrote"


def test_scores_from_real_runs(lru: StagedProblem) -> None:
    """A stage that fails an edge case first and fixes it scores it as
    caught; edge cases passed on the first run are hits."""
    t0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    attempts = staged.new_round(lru, t0)
    attempts[0].status, attempts[0].code = StageStatus.PASSED, {SOLUTION: lru.references[1]}
    attempts[1] = StageAttempt(status=StageStatus.ACTIVE, started_at=t0)
    buggy = MISTAKES["returns_expired_entries_still_in_the_map"][1](lru.references[2])
    assert staged.record_run(lru, attempts, _run(lru, buggy, 2)) is False
    assert staged.record_run(lru, attempts, _run(lru, lru.references[2], 2)) is True
    staged.finish_stage(
        attempts, StageStatus.PASSED, {SOLUTION: lru.references[2]}, t0.replace(minute=12)
    )
    result = staged.score_round(lru, attempts, t0.replace(minute=30))[1]
    assert result.runs == 2 and result.time_spent_s == 12 * 60
    assert {e.id: e.outcome for e in result.edge_cases} == {
        "expired_but_present": "caught",
        "put_resets_ttl": "hit",
    }
    assert result.design is not None and result.design.verdict == "extended"
