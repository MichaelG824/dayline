"""Shared fakes for the mock-interview tests: a scripted Anthropic client and
a small rubric."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
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
    # Defaults to "tool_use" when there is a tool call, else "end_turn".
    stop_reason: str = ""

    def __post_init__(self) -> None:
        if not self.stop_reason:
            calls = any(b.type == "tool_use" for b in self.content)
            self.stop_reason = "tool_use" if calls else "end_turn"


class FakeStream:
    """What ``client.messages.stream(...)`` returns: a context manager that
    iterates stream events (a text block's text arrives word by word) and
    then hands over the whole message. ``before_event`` runs before each
    event is yielded (tests use it to cancel mid-stream)."""

    def __init__(self, response: FakeResponse, before_event: Any = None) -> None:
        self._response = response
        self._before_event = before_event
        self.closed = False

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def __iter__(self) -> Iterator[Any]:
        for block in self._response.content:
            yield self._event(SimpleNamespace(type="content_block_start", content_block=block))
            if block.type == "text":
                words = block.text.split(" ")
                for i, word in enumerate(words):
                    text = word if i == len(words) - 1 else word + " "
                    delta = SimpleNamespace(type="text_delta", text=text)
                    yield self._event(SimpleNamespace(type="content_block_delta", delta=delta))
            yield self._event(SimpleNamespace(type="content_block_stop"))

    def _event(self, event: Any) -> Any:
        if self._before_event is not None:
            self._before_event(event)
        return event

    def get_final_message(self) -> FakeResponse:
        return self._response


@dataclass
class FakeMessages:
    """Returns the scripted responses in order and records every request.
    A scripted exception is raised instead of returned."""

    responses: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)
    before_event: Any = None
    streams: list[FakeStream] = field(default_factory=list)

    def _next(self, kwargs: dict[str, Any]) -> Any:
        # A copy of the messages: callers keep appending to their list.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def create(self, **kwargs: Any) -> FakeResponse:
        response: FakeResponse = self._next(kwargs)
        return response

    def stream(self, **kwargs: Any) -> FakeStream:
        stream = FakeStream(self._next(kwargs), self.before_event)
        self.streams.append(stream)
        return stream


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
