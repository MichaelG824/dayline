"""Grader: code decides what to trust in the model's scorecard."""

from __future__ import annotations

from typing import Any, cast

import pytest

from dayline.mock.grader import (
    MAX_ATTEMPTS,
    GradeInput,
    GradingError,
    grade_transcript,
    quote_in_transcript,
    weak_area_proposals,
)
from dayline.models import Category
from tests.mock_fakes import (
    TRANSCRIPT,
    FakeAnthropic,
    FakeMessages,
    FakeResponse,
    FakeText,
    FakeToolUse,
    scorecard_payload,
    small_rubric,
)


def _grade(client: FakeAnthropic, transcript: str = TRANSCRIPT) -> Any:
    data = GradeInput(transcript=transcript, rubric=small_rubric())
    return grade_transcript(cast(Any, client), "test-model", data, "session-1")


def test_valid_card_is_built_in_rubric_order_with_weighted_overall() -> None:
    payload = scorecard_payload()
    payload["criteria"].reverse()  # Model order must not matter.
    card = _grade(FakeAnthropic.replying(("submit_scorecard", payload)))

    assert [c.key for c in card.criteria] == ["reproduce", "ai_use"]
    assert [c.title for c in card.criteria] == ["Reproduces first", "Uses AI critically"]
    # Weights 1 and 3: (4*1 + 2*3) / 4 = 2.5, computed in code.
    assert card.overall_score == 2.5
    assert card.session_id == "session-1"
    assert card.grader_model == "test-model"


def test_evidence_not_in_transcript_is_kept_but_unverified() -> None:
    card = _grade(FakeAnthropic.replying(("submit_scorecard", scorecard_payload())))
    ai_use = card.criteria[1]
    assert [(e.quote, e.verified) for e in ai_use.evidence] == [
        ("The AI suggested a lock", True),
        ("I always verify AI output", False),
    ]


@pytest.mark.parametrize(
    "quote",
    [
        "let me run the TESTS first",  # case
        "Let me   run the tests\nfirst",  # whitespace
        "Candidate: Let me run the tests first",  # speaker label
        "[00:02] Let me run the tests first",  # timestamp
        "“Let me run the tests first.”",  # curly quotes + punctuation
        "The AI suggested a lock, but I don’t think",  # curly apostrophe
    ],
)
def test_quote_matching_tolerates_formatting(quote: str) -> None:
    assert quote_in_transcript(quote, TRANSCRIPT)


@pytest.mark.parametrize("quote", ["I used a mutex", "", "a"])
def test_quote_matching_rejects_invented_or_trivial_quotes(quote: str) -> None:
    assert not quote_in_transcript(quote, TRANSCRIPT)


def test_invalid_card_is_sent_back_with_the_problems_then_accepted() -> None:
    bad = scorecard_payload()
    bad["criteria"] = [
        {**bad["criteria"][0], "score": 7},
        {"key": "made_up", "score": 3, "evidence": [], "improvement": ""},
    ]
    client = FakeAnthropic.replying(
        ("submit_scorecard", bad), ("submit_scorecard", scorecard_payload())
    )
    card = _grade(client)

    assert card.overall_score == 2.5
    retry = client.messages.calls[1]["messages"][-1]["content"][0]
    assert retry["type"] == "tool_result" and retry["is_error"] is True
    assert "score must be an integer 1-4, got 7" in retry["content"]
    assert "Unknown criterion key 'made_up'" in retry["content"]
    assert "Missing criteria: ['ai_use']" in retry["content"]


def test_gives_up_after_max_attempts() -> None:
    bad = scorecard_payload(criteria=[])
    client = FakeAnthropic.replying(*[("submit_scorecard", bad)] * MAX_ATTEMPTS)
    with pytest.raises(GradingError, match="Missing criteria"):
        _grade(client)
    assert len(client.messages.calls) == MAX_ATTEMPTS


def test_duplicate_criterion_is_rejected() -> None:
    bad = scorecard_payload()
    bad["criteria"].append(dict(bad["criteria"][0]))
    client = FakeAnthropic.replying(*[("submit_scorecard", bad)] * MAX_ATTEMPTS)
    with pytest.raises(GradingError, match="scored more than once"):
        _grade(client)


@pytest.mark.parametrize("transcript", ["", "   \n"])
def test_empty_transcript_is_rejected_without_a_model_call(transcript: str) -> None:
    client = FakeAnthropic.replying()
    with pytest.raises(GradingError, match="empty"):
        _grade(client, transcript)
    assert client.messages.calls == []


def test_weak_areas_are_cleaned_and_become_linked_task_proposals() -> None:
    payload = scorecard_payload(
        weak_areas=[
            scorecard_payload()["weak_areas"][0],
            {  # Unknown category and an out-of-range duration degrade safely.
                "title": "Talk through tradeoffs",
                "why": "Silent for long stretches.",
                "task_name": "Mock: narrate a refactor out loud",
                "category": "Interview Prep",
                "est_duration_min": 600,
            },
            {"title": "No task name", "why": "", "category": "Behavioral"},
        ]
    )
    card = _grade(FakeAnthropic.replying(("submit_scorecard", payload)))

    assert [(w.category, w.est_duration_min) for w in card.weak_areas] == [
        (Category.SYSTEM_DESIGN, 45),
        (Category.OTHER, 45),
    ]
    proposals = weak_area_proposals(card)
    assert proposals[0] == {
        "type": "propose_new_task",
        "id": f"mock-{card.id}-0",
        "name": "Practise explaining race conditions and row locks",
        "category": "System Design",
        "priority": "P1",
        "est_duration_min": 45,
        "reason": "Could not answer the race-condition follow-up.",
        "mock_session_id": "session-1",
    }


def test_request_forces_the_scorecard_tool_and_includes_rubric_and_transcript() -> None:
    client = FakeAnthropic.replying(("submit_scorecard", scorecard_payload()))
    _grade(client)
    call = client.messages.calls[0]
    assert "tool_choice" not in call
    assert [t["name"] for t in call["tools"]] == ["submit_scorecard"]
    prompt = call["messages"][0]["content"]
    assert "key `ai_use`" in prompt and "(weight 3)" in prompt
    assert "<transcript>" in prompt and "Let me run the tests first" in prompt


def test_prose_reply_is_nudged_and_counts_as_an_attempt() -> None:
    client = FakeAnthropic(
        FakeMessages(
            [
                FakeResponse([FakeText("Overall the candidate did well...")]),
                FakeResponse([FakeToolUse("submit_scorecard", scorecard_payload())]),
            ]
        )
    )
    card = _grade(client)
    assert card.overall_score == 2.5
    nudge = client.messages.calls[1]["messages"][-1]
    assert nudge["role"] == "user" and "submit_scorecard" in nudge["content"]
