"""Shared fakes for the mock-interview tests: a scripted Anthropic client and
a small rubric."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dayline.models import MockRubric, RubricCriterion


@dataclass
class FakeToolUse:
    name: str
    input: dict[str, Any]
    id: str = "tu_1"
    type: str = "tool_use"


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list[Any]


@dataclass
class FakeMessages:
    """Returns the scripted responses in order and records every request."""

    responses: list[FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self.responses.pop(0)


@dataclass
class FakeAnthropic:
    messages: FakeMessages

    @classmethod
    def replying(cls, *tool_calls: tuple[str, dict[str, Any]]) -> FakeAnthropic:
        """A client whose Nth call returns the Nth (tool name, input) as a tool_use block."""
        return cls(
            FakeMessages(
                [
                    FakeResponse([FakeToolUse(name=name, input=payload, id=f"tu_{i}")])
                    for i, (name, payload) in enumerate(tool_calls)
                ]
            )
        )


def small_rubric() -> MockRubric:
    return MockRubric(
        id="rubric-1",
        name="AI-assisted coding",
        criteria=[
            RubricCriterion(key="reproduce", title="Reproduces first", description="", weight=1),
            RubricCriterion(key="ai_use", title="Uses AI critically", description="", weight=3),
        ],
    )


TRANSCRIPT = """[00:01] Interviewer: The checkout endpoint lets two people borrow the same book.
[00:02] Candidate: Let me run the tests first to see what fails.
[03:10] Candidate: The AI suggested a lock, but I don't think we need one here.
[09:45] Interviewer: What if two requests arrive at the same time?
[09:50] Candidate: Hmm, I'm not sure."""


def scorecard_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": "Solid debugging, weak on concurrency.",
        "strengths": ["Ran the tests before changing code"],
        "criteria": [
            {
                "key": "reproduce",
                "score": 4,
                "evidence": ["Let me run the tests first to see what fails."],
                "improvement": "Keep doing this.",
            },
            {
                "key": "ai_use",
                "score": 2,
                "evidence": ["The AI suggested a lock", "I always verify AI output"],
                "improvement": "Explain why you reject a suggestion.",
            },
        ],
        "weak_areas": [
            {
                "title": "Concurrency basics",
                "why": "Could not answer the race-condition follow-up.",
                "task_name": "Practise explaining race conditions and row locks",
                "category": "System Design",
                "est_duration_min": 45,
            }
        ],
    }
    payload.update(overrides)
    return payload
