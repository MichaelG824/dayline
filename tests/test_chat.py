"""Chat analysis-first tools: read shapes, propose collection, confirm apply."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from dayline.adapters.outcomes import (
    OUTCOME_PROPOSAL_ACCEPTED,
    InMemoryOutcomesStore,
)
from dayline.adapters.preferences import InMemoryPreferencesStore, PlannerPreferences
from dayline.adapters.task_source import InMemoryTaskSource
from dayline.api.chat import (
    _PROPOSE_TOOL_NAMES,
    _READ_TOOL_NAMES,
    TOOLS,
    ChatDeps,
    apply_proposal,
    run_chat_turn,
    stream_chat_turn,
)
from dayline.models import Category, Priority, Status
from tests.fixtures import task

DAY = date(2026, 9, 8)


@dataclass
class _FakeText:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeToolUse:
    type: str = "tool_use"
    id: str = "tu_1"
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeResponse:
    content: list[Any]


def _make_deps(
    tasks: list | None = None,
    prefs: PlannerPreferences | None = None,
) -> tuple[ChatDeps, InMemoryTaskSource, InMemoryPreferencesStore, InMemoryOutcomesStore]:
    source = InMemoryTaskSource(tasks or [])
    pref_store = InMemoryPreferencesStore(prefs)
    outcome_store = InMemoryOutcomesStore()

    def get_plan(day: date) -> dict[str, Any]:
        return {
            "day": day.isoformat(),
            "brief": "1 block",
            "blocks": [
                {
                    "taskId": "t1",
                    "title": "[dayline] DSA",
                    "start": "2026-09-08T09:00:00",
                    "end": "2026-09-08T10:00:00",
                }
            ],
            "unplaced": [],
        }

    def list_interviews() -> list[dict[str, Any]]:
        return [
            {
                "id": "iv1",
                "company": "Acme",
                "role": "SWE",
                "category": "System Design",
                "scheduledAt": "2026-09-10T15:00:00+00:00",
                "applicationId": "app1",
            }
        ]

    def get_category_ranks() -> list[dict[str, Any]]:
        return [
            {"category": "AI Coding - React/Python", "rank": 1},
            {"category": "AI Coding - DSA", "rank": 2},
            {"category": "Behavioral", "rank": 3},
            {"category": "System Design", "rank": 4},
            {"category": "Leetcode", "rank": 5},
        ]

    deps = ChatDeps(
        task_source=source,
        get_plan=get_plan,
        list_interviews=list_interviews,
        get_category_ranks=get_category_ranks,
        get_preferences=lambda: pref_store.get_preferences().to_dict(),
        get_recent_outcomes=lambda limit: [
            e.to_dict() for e in outcome_store.list_recent(limit=limit)
        ],
        apply_preference_update=lambda patch: pref_store.patch_preferences(patch).to_dict(),
        apply_category_ranks=lambda ranks: ranks,
        preferences_snapshot=pref_store.get_preferences().to_dict(),
    )
    return deps, source, pref_store, outcome_store


def test_tool_registry_splits_read_and_propose() -> None:
    names = {t["name"] for t in TOOLS}
    assert names >= _READ_TOOL_NAMES
    assert names >= _PROPOSE_TOOL_NAMES
    assert _READ_TOOL_NAMES.isdisjoint(_PROPOSE_TOOL_NAMES)


def test_analyze_only_returns_explanation_empty_proposals() -> None:
    deps, *_ = _make_deps()
    client = MagicMock()
    client.messages.create.return_value = _FakeResponse(
        content=[
            _FakeText(
                text="Situation: light day.\nRisks: none.\nRecommendation: keep course."
            )
        ]
    )

    result = run_chat_turn(client, deps, DAY, "How's my plan looking?")

    assert "Situation" in result.explanation or "light day" in result.explanation
    assert result.proposals == []
    assert client.messages.create.called


def test_read_tools_auto_execute_stable_json_shapes() -> None:
    deps, source, pref_store, outcome_store = _make_deps(
        tasks=[
            task(
                "t1",
                name="DSA drills",
                category=Category.AI_CODING_DSA,
                priority=Priority.P0,
                duration=60,
            )
        ],
        prefs=PlannerPreferences(peak_hours="9-12", standing_rules=["mornings = DSA"]),
    )
    outcome_store.log_outcome(OUTCOME_PROPOSAL_ACCEPTED, {"proposalType": "propose_new_task"})

    client = MagicMock()
    # Turn 1: model calls several read tools; turn 2: text-only analysis.
    client.messages.create.side_effect = [
        _FakeResponse(
            content=[
                _FakeToolUse(id="a", name="list_tasks", input={}),
                _FakeToolUse(id="b", name="get_plan", input={"day": DAY.isoformat()}),
                _FakeToolUse(id="c", name="list_interviews", input={}),
                _FakeToolUse(id="d", name="get_category_ranks", input={}),
                _FakeToolUse(id="e", name="get_preferences", input={}),
                _FakeToolUse(id="f", name="get_recent_outcomes", input={"limit": 5}),
            ]
        ),
        _FakeResponse(content=[_FakeText(text="Analysis complete.")]),
    ]

    result = run_chat_turn(client, deps, DAY, "Analyze everything")

    assert result.explanation == "Analysis complete."
    assert result.proposals == []
    # Second user message carries tool_results.
    tool_round = result.history[2]["content"]
    by_id = {tr["tool_use_id"]: tr["content"] for tr in tool_round}

    import json

    tasks_json = json.loads(by_id["a"])
    assert tasks_json[0]["id"] == "t1"
    assert tasks_json[0]["status"] == Status.BACKLOG.value
    assert "estDurationMin" in tasks_json[0]

    plan_json = json.loads(by_id["b"])
    assert plan_json["day"] == DAY.isoformat()
    assert "blocks" in plan_json and "brief" in plan_json

    interviews = json.loads(by_id["c"])
    assert interviews[0]["company"] == "Acme"
    assert "scheduledAt" in interviews[0]

    ranks = json.loads(by_id["d"])
    assert ranks[0]["rank"] == 1

    prefs = json.loads(by_id["e"])
    assert prefs["peakHours"] == "9-12"
    assert "mornings = DSA" in prefs["standingRules"]

    outcomes = json.loads(by_id["f"])
    assert outcomes[0]["kind"] == OUTCOME_PROPOSAL_ACCEPTED
    assert "payload" in outcomes[0]


def test_read_tool_loop_is_bounded() -> None:
    """A model that keeps calling read tools can't spin forever on paid calls."""
    from dayline.api.chat import MAX_TOOL_ROUNDS

    deps, *_ = _make_deps()
    client = MagicMock()
    # Every response only ever calls a read tool, never returns final text.
    client.messages.create.return_value = _FakeResponse(
        content=[_FakeToolUse(id="a", name="list_tasks", input={})]
    )

    result = run_chat_turn(client, deps, DAY, "loop forever")

    assert client.messages.create.call_count == MAX_TOOL_ROUNDS
    assert result.proposals == []


def test_propose_path_collects_without_applying() -> None:
    deps, source, *_ = _make_deps(
        tasks=[
            task("t1", name="Leetcode", category=Category.LEETCODE, duration=30),
        ]
    )
    client = MagicMock()
    client.messages.create.return_value = _FakeResponse(
        content=[
            _FakeText(text="Here are changes."),
            _FakeToolUse(
                id="p1",
                name="propose_duration_change",
                input={
                    "task_id": "t1",
                    "task_name": "Leetcode",
                    "new_duration_min": 45,
                    "reason": "more reps",
                },
            ),
            _FakeToolUse(
                id="p2",
                name="propose_new_task",
                input={
                    "name": "Behavioral stories",
                    "category": "Behavioral",
                    "est_duration_min": 30,
                    "reason": "interview soon",
                },
            ),
            _FakeToolUse(
                id="p3",
                name="propose_new_task",
                input={
                    "name": "System design notes",
                    "category": "System Design",
                    "est_duration_min": 60,
                    "reason": "brain dump",
                },
            ),
        ]
    )

    result = run_chat_turn(client, deps, DAY, "brain dump prep")

    assert len(result.proposals) == 3
    assert result.proposals[0]["type"] == "propose_duration_change"
    assert {p["type"] for p in result.proposals[1:]} == {"propose_new_task"}
    # Nothing applied until confirm.
    assert source.get_task("t1").est_duration_min == 30
    assert len(source.list_tasks()) == 1


def test_apply_proposals_mutates_only_on_confirm() -> None:
    deps, source, pref_store, _ = _make_deps(
        tasks=[
            task("t1", name="Leetcode", category=Category.LEETCODE, duration=30),
        ]
    )

    apply_proposal(
        deps,
        {
            "type": "propose_duration_change",
            "task_id": "t1",
            "new_duration_min": 50,
        },
    )
    assert source.get_task("t1").est_duration_min == 50

    created = apply_proposal(
        deps,
        {
            "type": "propose_new_task",
            "name": "Mock behavioral",
            "category": "Behavioral",
            "est_duration_min": 40,
            "priority": "P1",
        },
    )
    assert created["result"] == "ok"
    assert any(t.name == "Mock behavioral" for t in source.list_tasks())

    apply_proposal(
        deps,
        {
            "type": "propose_reprioritization",
            "task_id": "t1",
            "new_priority": "P0",
        },
    )
    assert source.get_task("t1").priority == Priority.P0

    prefs = apply_proposal(
        deps,
        {
            "type": "propose_preference_update",
            "peak_hours": "6-10",
            "standing_rules": ["evenings = leetcode"],
            "reason": "user said so",
        },
    )
    assert prefs["preferences"]["peakHours"] == "6-10"
    assert pref_store.get_preferences().peak_hours == "6-10"

    ranks = apply_proposal(
        deps,
        {
            "type": "propose_category_rank_change",
            "ranks": [{"category": "Leetcode", "rank": 1}],
            "reason": "outcome nudge",
        },
    )
    assert ranks["result"] == "ok"


def test_apply_unknown_proposal_raises() -> None:
    deps, *_ = _make_deps()
    with pytest.raises(ValueError, match="Unknown proposal"):
        apply_proposal(deps, {"type": "propose_explode"})


def test_preferences_store_roundtrip() -> None:
    store = InMemoryPreferencesStore()
    store.patch_preferences(
        {
            "peakHours": "8-11",
            "categoryCaps": {"Leetcode": 90},
            "standingRules": ["mornings = DSA"],
            "freeText": "no meetings before noon",
        }
    )
    got = store.get_preferences()
    assert got.peak_hours == "8-11"
    assert got.category_caps["Leetcode"] == 90
    assert got.standing_rules == ["mornings = DSA"]
    assert got.free_text == "no meetings before noon"


def test_outcomes_store_newest_first() -> None:
    store = InMemoryOutcomesStore()
    store.log_outcome("a", {"n": 1})
    store.log_outcome("b", {"n": 2})
    recent = store.list_recent(limit=1)
    assert len(recent) == 1
    assert recent[0].kind == "b"


# --- streaming turn (stream_chat_turn) -------------------------------------


class _FakeStream:
    """Stands in for the SDK's ``messages.stream`` context manager."""

    def __init__(self, texts: list[str], final: _FakeResponse) -> None:
        self.text_stream = iter(texts)
        self._final = final

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def get_final_message(self) -> _FakeResponse:
        return self._final


def _stream_client(*rounds: tuple[list[str], list[Any]]) -> MagicMock:
    """MagicMock client whose ``messages.stream`` replays (texts, blocks) rounds."""
    client = MagicMock()
    streams = [_FakeStream(texts, _FakeResponse(content=blocks)) for texts, blocks in rounds]
    if len(streams) == 1:
        client.messages.stream.side_effect = lambda **_: _FakeStream(
            list(rounds[0][0]), _FakeResponse(content=rounds[0][1])
        )
    else:
        client.messages.stream.side_effect = streams
    return client


def _drain(events: Any) -> tuple[list[tuple[str, Any]], Any]:
    collected = list(events)
    assert collected[-1][0] == "result"
    return collected[:-1], collected[-1][1]


def test_stream_yields_text_deltas_in_order() -> None:
    deps, *_ = _make_deps()
    client = _stream_client(
        (["Situation: ", "light ", "day."], [_FakeText(text="Situation: light day.")])
    )

    events, result = _drain(stream_chat_turn(client, deps, DAY, "How's my plan?"))

    assert [text for kind, text in events if kind == "delta"] == [
        "Situation: ",
        "light ",
        "day.",
    ]
    assert result.explanation == "Situation: light day."
    assert result.proposals == []


def test_stream_read_tool_round_emits_status_and_continues() -> None:
    deps, *_ = _make_deps()
    client = _stream_client(
        ([], [_FakeToolUse(id="a", name="list_tasks"), _FakeToolUse(id="b", name="get_plan")]),
        (["All good."], [_FakeText(text="All good.")]),
    )

    events, result = _drain(stream_chat_turn(client, deps, DAY, "analyze"))

    statuses = [msg for kind, msg in events if kind == "status"]
    assert len(statuses) == 1
    assert statuses[0] == "Reading your tasks and your plan..."
    assert client.messages.stream.call_count == 2
    assert result.explanation == "All good."
    # Tool results were round-tripped back to the model.
    tool_round = result.history[2]["content"]
    assert {tr["tool_use_id"] for tr in tool_round} == {"a", "b"}


def test_stream_propose_stops_loop_and_lands_in_result() -> None:
    deps, *_ = _make_deps(
        tasks=[task("t1", name="Leetcode", category=Category.LEETCODE, duration=30)]
    )
    client = _stream_client(
        (
            ["Here are changes."],
            [
                _FakeText(text="Here are changes."),
                _FakeToolUse(
                    id="p1",
                    name="propose_duration_change",
                    input={
                        "task_id": "t1",
                        "task_name": "Leetcode",
                        "new_duration_min": 45,
                        "reason": "more reps",
                    },
                ),
            ],
        ),
    )

    events, result = _drain(stream_chat_turn(client, deps, DAY, "bump leetcode"))

    assert [msg for kind, msg in events if kind == "status"] == []
    assert client.messages.stream.call_count == 1
    assert result.proposals == [
        {
            "type": "propose_duration_change",
            "id": "p1",
            "task_id": "t1",
            "task_name": "Leetcode",
            "new_duration_min": 45,
            "reason": "more reps",
        }
    ]
    # Still a proposal only - nothing applied.
    assert result.explanation == "Here are changes."


def test_stream_read_tool_loop_is_bounded() -> None:
    from dayline.api.chat import MAX_TOOL_ROUNDS

    deps, *_ = _make_deps()
    client = _stream_client(([], [_FakeToolUse(id="a", name="list_tasks")]))

    _events, result = _drain(stream_chat_turn(client, deps, DAY, "loop forever"))

    assert client.messages.stream.call_count == MAX_TOOL_ROUNDS
    assert result.proposals == []
