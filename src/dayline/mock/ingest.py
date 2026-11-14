"""Turn a pasted interview report into structured questions, and find likely
duplicates already in the bank.

Extraction is one tool call (``record_questions``, see ``mock/llm.py``), so the
model returns the schema rather than prose. One post often covers several rounds, so
it returns a list. Nothing is saved here: the user reviews each extracted
question (and any suggested duplicate) before it reaches the bank.

Duplicate detection is a cheap shortlist, not a decision: fuzzy similarity on
the English title and prompt against canonical questions only. The user picks
"same as" or "new" - the merge is never automatic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import anthropic
from rapidfuzz import fuzz

from dayline.mock.llm import request_tool_call
from dayline.models import MockQuestion, MockRoundType

# A long forum thread is fine; a whole saved web page is not what this is for.
MAX_POST_CHARS = 30_000

# A suggested duplicate must score at least this (0-100), and at most this
# many are shown. Loose on purpose: a missed duplicate costs more than one
# extra suggestion the user dismisses.
MIN_SIMILARITY = 60.0
MAX_SUGGESTIONS = 3

SYSTEM_PROMPT = """You extract interview questions from interview reports \
(often 1point3acres posts, often in Chinese, often informal).

Rules:
- Write every field in English. Translate faithfully; keep code, identifiers, \
and technical terms as written.
- Extract one entry per distinct question or round that has enough detail to \
practise. Skip pure logistics (scheduling, recruiter chat, compensation).
- Never invent details the post does not contain. If the company, role, or \
date is not stated, leave it null.
- prompt_md: the question as an interviewer would state it, in Markdown. \
Include the example inputs/outputs or the starting setup if the post gives them.
- follow_ups: questions the interviewer asked after the main task, in order.
- constraints: explicit limits (time limit, allowed tools, language, \
complexity targets).
- round_type must be one of the allowed values; pick the closest.
- original_language: ISO 639-1 code of the post's main language (e.g. "zh", "en").

Always respond by calling record_questions."""

RECORD_TOOL: dict[str, Any] = {
    "name": "record_questions",
    "description": "Record every practisable interview question found in the post.",
    "input_schema": {
        "type": "object",
        "properties": {
            "original_language": {"type": "string"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short, specific name"},
                        "company": {"type": ["string", "null"]},
                        "role": {"type": ["string", "null"]},
                        "round_type": {
                            "type": "string",
                            "enum": [r.value for r in MockRoundType],
                        },
                        "prompt_md": {"type": "string"},
                        "constraints": {"type": "array", "items": {"type": "string"}},
                        "follow_ups": {"type": "array", "items": {"type": "string"}},
                        "language_hint": {
                            "type": ["string", "null"],
                            "description": "Programming language if stated, e.g. python",
                        },
                        "reported_on": {
                            "type": ["string", "null"],
                            "description": "Interview date as YYYY-MM-DD, if stated",
                        },
                    },
                    "required": ["title", "round_type", "prompt_md"],
                },
            },
        },
        "required": ["original_language", "questions"],
    },
}


class ExtractionError(ValueError):
    """The post could not be turned into questions (bad input or bad model output)."""


@dataclass(slots=True)
class ExtractedQuestion:
    """One question pulled from a post, not yet saved."""

    title: str
    round_type: MockRoundType
    prompt_md: str
    company: str | None = None
    role: str | None = None
    constraints: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    language_hint: str | None = None
    reported_on: date | None = None


@dataclass(slots=True)
class Extraction:
    original_language: str | None
    questions: list[ExtractedQuestion]


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [s.strip() for s in value if isinstance(s, str) and s.strip()]


def _parse_reported_on(value: Any) -> date | None:
    # The model sometimes writes partial dates ("2026-10"); drop rather than guess.
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _parse_question(raw: Any) -> ExtractedQuestion | None:
    if not isinstance(raw, dict):
        return None
    title = _clean_str(raw.get("title"))
    prompt = _clean_str(raw.get("prompt_md"))
    if not title or not prompt:
        return None
    try:
        round_type = MockRoundType(str(raw.get("round_type")))
    except ValueError:
        return None
    return ExtractedQuestion(
        title=title,
        round_type=round_type,
        prompt_md=prompt,
        company=_clean_str(raw.get("company")),
        role=_clean_str(raw.get("role")),
        constraints=_clean_list(raw.get("constraints")),
        follow_ups=_clean_list(raw.get("follow_ups")),
        language_hint=_clean_str(raw.get("language_hint")),
        reported_on=_parse_reported_on(raw.get("reported_on")),
    )


def extract_questions(client: anthropic.Anthropic, model: str, post: str) -> Extraction:
    """Extract every practisable question from ``post``.

    Raises :class:`ExtractionError` for empty/oversized input or when the
    model returns nothing usable.
    """
    text = post.strip()
    if not text:
        raise ExtractionError("Paste the post text first")
    if len(text) > MAX_POST_CHARS:
        raise ExtractionError(
            f"Post is {len(text):,} characters; paste at most {MAX_POST_CHARS:,} "
            "(just the interview part of the thread)"
        )

    tool_use = request_tool_call(
        client,
        model=model,
        system=SYSTEM_PROMPT,
        tool=RECORD_TOOL,
        messages=[{"role": "user", "content": text}],
    )
    if tool_use is None:
        raise ExtractionError("The model did not return any questions; try again")
    payload: dict[str, Any] = dict(tool_use.input or {})
    raw_questions = payload.get("questions")
    parsed = [_parse_question(q) for q in raw_questions] if isinstance(raw_questions, list) else []
    questions = [q for q in parsed if q]
    if not questions:
        raise ExtractionError("No practisable questions found in that post")
    return Extraction(
        original_language=_clean_str(payload.get("original_language")),
        questions=questions,
    )


_NON_WORD = re.compile(r"[^\w]+")


def _normalize(text: str) -> str:
    """Lowercase, drop Markdown/punctuation, collapse whitespace."""
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def similarity(title_a: str, prompt_a: str, title_b: str, prompt_b: str) -> float:
    """0-100 similarity of two questions.

    Titles are short and paraphrased, so token_set_ratio (word overlap, order
    ignored) suits them. Prompts are compared on their first 1,000 characters,
    which is where the actual task is stated; later detail varies by reporter.
    The prompt counts more because two different questions can share a
    generic title ("LRU cache" vs "LRU cache with TTL").
    """
    titles = fuzz.token_set_ratio(_normalize(title_a), _normalize(title_b))
    prompts = fuzz.token_set_ratio(_normalize(prompt_a)[:1000], _normalize(prompt_b)[:1000])
    return round(0.4 * titles + 0.6 * prompts, 1)


def find_similar(
    title: str, prompt_md: str, bank: list[MockQuestion]
) -> list[tuple[MockQuestion, float]]:
    """Canonical questions in ``bank`` that may be the same question, best first."""
    scored = [
        (q, similarity(title, prompt_md, q.title, q.prompt_md))
        for q in bank
        if q.canonical_id is None
    ]
    matches = [(q, s) for q, s in scored if s >= MIN_SIMILARITY]
    matches.sort(key=lambda pair: (-pair[1], pair[0].title))
    return matches[:MAX_SUGGESTIONS]
