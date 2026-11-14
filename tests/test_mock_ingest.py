"""Ingest: extraction parsing and duplicate suggestions."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from dayline.mock.ingest import (
    MAX_POST_CHARS,
    ExtractionError,
    extract_questions,
    find_similar,
    similarity,
)
from dayline.models import MockQuestion, MockRoundType
from tests.mock_fakes import FakeAnthropic, FakeMessages, FakeResponse, FakeText, FakeToolUse

POST = "店面第一轮: 给一个图书馆 Flask app, 修 checkout bug, 然后加 late fee. 追问 race condition."

LIBRARY = {
    "title": "Fix library checkout bug, then add late fees",
    "company": " Acme ",
    "role": None,
    "round_type": "AI-assisted project",
    "prompt_md": "You get a small Flask library app. Two members can check out the same book.",
    "constraints": ["45 minutes", "  ", "AI assistant allowed"],
    "follow_ups": ["What if two requests arrive at once?"],
    "language_hint": "python",
    "reported_on": "2026-10",  # Partial date: dropped, not guessed.
}


def _extract(*payloads: dict[str, Any]) -> Any:
    client = FakeAnthropic.replying(*[("record_questions", p) for p in payloads])
    return extract_questions(cast(Any, client), "test-model", POST), client


def test_extracts_and_cleans_questions() -> None:
    extraction, client = _extract({"original_language": "zh", "questions": [LIBRARY]})
    assert extraction.original_language == "zh"
    [q] = extraction.questions
    assert q.round_type is MockRoundType.AI_ASSISTED_PROJECT
    assert q.company == "Acme"
    assert q.constraints == ["45 minutes", "AI assistant allowed"]
    assert q.reported_on is None
    call = client.messages.calls[0]
    # The models reject a forced tool_choice, so the tool is only offered.
    assert "tool_choice" not in call
    assert [t["name"] for t in call["tools"]] == ["record_questions"]


def test_keeps_full_dates_and_drops_unusable_entries() -> None:
    extraction, _ = _extract(
        {
            "original_language": "en",
            "questions": [
                {**LIBRARY, "reported_on": "2026-10-03"},
                {**LIBRARY, "round_type": "Take-home"},  # Not an allowed round type.
                {**LIBRARY, "prompt_md": "  "},  # No prompt.
                "not an object",
            ],
        }
    )
    assert [q.reported_on for q in extraction.questions] == [date(2026, 10, 3)]


def test_no_usable_questions_is_an_error() -> None:
    with pytest.raises(ExtractionError, match="No practisable questions"):
        _extract({"original_language": "zh", "questions": []})


def test_prose_reply_is_nudged_once_then_accepted() -> None:
    client = FakeAnthropic(
        FakeMessages(
            [
                FakeResponse([FakeText("Here are the questions: ...")]),
                FakeResponse(
                    [
                        FakeToolUse(
                            "record_questions", {"original_language": "zh", "questions": [LIBRARY]}
                        )
                    ]
                ),
            ]
        )
    )
    extraction = extract_questions(cast(Any, client), "test-model", POST)
    assert len(extraction.questions) == 1
    retry = client.messages.calls[1]["messages"]
    assert retry[-1]["role"] == "user" and "record_questions" in retry[-1]["content"]


def test_model_that_never_calls_the_tool_is_an_error() -> None:
    client = FakeAnthropic(
        FakeMessages([FakeResponse([FakeText("Sorry")]), FakeResponse([FakeText("Sorry")])])
    )
    with pytest.raises(ExtractionError, match="did not return"):
        extract_questions(cast(Any, client), "test-model", POST)


@pytest.mark.parametrize(
    ("post", "message"), [("   ", "Paste the post"), ("x" * (MAX_POST_CHARS + 1), "at most")]
)
def test_bad_input_is_rejected_without_a_model_call(post: str, message: str) -> None:
    client = FakeAnthropic.replying()
    with pytest.raises(ExtractionError, match=message):
        extract_questions(cast(Any, client), "test-model", post)
    assert client.messages.calls == []


def _question(qid: str, title: str, prompt: str, canonical_id: str | None = None) -> MockQuestion:
    return MockQuestion(
        id=qid,
        title=title,
        round_type=MockRoundType.ALGORITHM,
        prompt_md=prompt,
        canonical_id=canonical_id,
    )


LRU_PROMPT = "Design a data structure for a least recently used cache with get and put in O(1)."


def test_paraphrased_report_scores_high_and_different_question_scores_low() -> None:
    same = similarity(
        "LRU cache",
        LRU_PROMPT,
        "Implement an LRU Cache",
        "Implement a least-recently-used (LRU) cache: get and put, both O(1).",
    )
    different = similarity(
        "LRU cache", LRU_PROMPT, "Merge intervals", "Given intervals, merge all overlapping ones."
    )
    assert same >= 60 > different


def test_find_similar_only_suggests_canonical_questions_best_first() -> None:
    bank = [
        _question("q1", "LRU cache", LRU_PROMPT),
        _question("q2", "LRU cache (reported again)", LRU_PROMPT, canonical_id="q1"),
        _question("q3", "Merge intervals", "Given intervals, merge all overlapping ones."),
        _question("q4", "LRU cache with TTL", LRU_PROMPT + " Entries also expire after a TTL."),
    ]
    matches = find_similar("Implement LRU cache", LRU_PROMPT, bank)
    assert [q.id for q, _ in matches] == ["q1", "q4"]
    assert matches[0][1] >= matches[1][1]
