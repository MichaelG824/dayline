"""Grade a mock-interview transcript against a rubric.

The model fills in one tool call (``submit_scorecard``, see ``mock/llm.py``). Code - not the
model - then decides what to trust:

- Every rubric criterion must be scored exactly once, 1-4. A malformed card is
  sent back to the model with the problems listed, up to ``MAX_ATTEMPTS``.
- Every evidence quote is checked against the transcript. A quote that does
  not appear there is kept but marked ``verified=False`` so the UI can flag it;
  the grader cannot invent evidence silently.
- The overall score is the weighted mean of criterion scores, computed here.

Weak areas become ``propose_new_task`` proposals (see :func:`weak_area_proposals`)
that go through the existing chat confirm path - grading never creates tasks.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, cast

import anthropic

from dayline.mock.llm import find_tool_use, nudge
from dayline.models import (
    Category,
    CriterionScore,
    Evidence,
    MockGuideline,
    MockQuestion,
    MockRubric,
    Priority,
    Scorecard,
    WeakArea,
)

MAX_TRANSCRIPT_CHARS = 200_000
# Each attempt is one model call: a prose reply or an invalid card uses one up.
MAX_ATTEMPTS = 3
MAX_WEAK_AREAS = 4
MIN_SCORE, MAX_SCORE = 1, 4
# Weak areas are prep work, so never Errand/Other.
_PREP_CATEGORY_VALUES = [c.value for c in Category if c.is_prep]

SCORE_SCALE = """Score scale (integers only):
1 = not demonstrated, or done poorly
2 = partly demonstrated; clear gaps
3 = solid; meets the bar for a mid/senior hire
4 = strong; clearly above the bar, with specific evidence"""

SYSTEM_PROMPT = f"""You are a strict, fair interview grader. You grade one \
mock-interview transcript against a rubric and the candidate's own standards.

{SCORE_SCALE}

Rules:
- Score every rubric criterion exactly once, using its key.
- Evidence must be short verbatim quotes copied from the transcript (a phrase \
or sentence, not a paraphrase). Prefer 1-3 quotes per criterion. If the \
transcript shows nothing for a criterion, give no quotes and score it low.
- improvement: one specific, actionable change for next time.
- weak_areas: at most {MAX_WEAK_AREAS} things to practise next, each phrased \
as a concrete prep task (task_name) with a realistic duration in minutes.
- Be honest. Do not inflate scores to be encouraging.

Always respond by calling submit_scorecard."""

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_scorecard",
    "description": "Submit the graded scorecard.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "2-4 sentence overall verdict"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "score": {"type": "integer", "minimum": MIN_SCORE, "maximum": MAX_SCORE},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "improvement": {"type": "string"},
                    },
                    "required": ["key", "score", "evidence", "improvement"],
                },
            },
            "weak_areas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "why": {"type": "string"},
                        "task_name": {"type": "string"},
                        "category": {"type": "string", "enum": _PREP_CATEGORY_VALUES},
                        "est_duration_min": {"type": "integer", "minimum": 15, "maximum": 180},
                    },
                    "required": ["title", "why", "task_name", "category", "est_duration_min"],
                },
            },
        },
        "required": ["summary", "strengths", "criteria", "weak_areas"],
    },
}


class GradingError(ValueError):
    """The transcript could not be graded (bad input, or the model never
    produced a valid scorecard)."""


@dataclass(slots=True)
class GradeInput:
    transcript: str
    rubric: MockRubric
    guideline: MockGuideline | None = None
    question: MockQuestion | None = None


_QUOTE_CHARS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_SPACE = re.compile(r"\s+")
# Speaker labels and timestamps ("Interviewer:", "[12:40]") that a model may
# include in or strip from a quote; ignored when matching.
_LABEL = re.compile(r"\[?\d{1,2}:\d{2}(?::\d{2})?\]?|^\s*\w+:\s*")


def _normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS).lower()
    text = _LABEL.sub(" ", text)
    return _SPACE.sub(" ", text).strip(" .,!?;:\"'")


def quote_in_transcript(quote: str, transcript: str) -> bool:
    """True when ``quote`` appears in ``transcript``, ignoring case, whitespace,
    curly quotes, surrounding punctuation, and speaker labels/timestamps."""
    needle = _normalize_for_match(quote)
    if len(needle) < 3:
        return False
    haystack = " ".join(_normalize_for_match(line) for line in transcript.splitlines())
    return needle in haystack


def weighted_overall(criteria: list[CriterionScore], rubric: MockRubric) -> float:
    weights = {c.key: c.weight for c in rubric.criteria}
    total = sum(weights[c.key] for c in criteria)
    if total <= 0:
        return 0.0
    return round(sum(c.score * weights[c.key] for c in criteria) / total, 2)


def _user_message(data: GradeInput) -> str:
    rubric_lines = "\n".join(
        f"- key `{c.key}` - {c.title} (weight {c.weight:g}): {c.description}"
        for c in data.rubric.criteria
    )
    parts = [f"## Rubric: {data.rubric.name}\n{rubric_lines}"]
    if data.guideline and data.guideline.body_md.strip():
        parts.append(f"## Candidate's grading standards\n{data.guideline.body_md.strip()}")
    if data.question:
        q = data.question
        detail = [f"## Question: {q.title} ({q.round_type.value})", q.prompt_md]
        if q.follow_ups:
            detail.append("Expected follow-ups:\n" + "\n".join(f"- {f}" for f in q.follow_ups))
        parts.append("\n".join(detail))
    parts.append(f"## Transcript\n<transcript>\n{data.transcript.strip()}\n</transcript>")
    return "\n\n".join(parts)


def _validate(payload: dict[str, Any], rubric: MockRubric) -> list[str]:
    """Problems with the model's scorecard, as messages it can act on."""
    problems: list[str] = []
    expected = [c.key for c in rubric.criteria]
    seen: list[str] = []
    for item in payload.get("criteria") or []:
        key = item.get("key") if isinstance(item, dict) else None
        if key not in expected:
            problems.append(f"Unknown criterion key {key!r}; use only {expected}")
            continue
        if key in seen:
            problems.append(f"Criterion {key!r} scored more than once")
        seen.append(key)
        score = item.get("score")
        if not isinstance(score, int) or not MIN_SCORE <= score <= MAX_SCORE:
            problems.append(f"Criterion {key!r} score must be an integer 1-4, got {score!r}")
    missing = [k for k in expected if k not in seen]
    if missing:
        problems.append(f"Missing criteria: {missing}")
    return problems


def _weak_area(raw: Any) -> WeakArea | None:
    if not isinstance(raw, dict) or not raw.get("task_name"):
        return None
    try:
        category = Category(str(raw.get("category")))
    except ValueError:
        category = Category.OTHER
    duration = raw.get("est_duration_min")
    minutes = duration if isinstance(duration, int) and 15 <= duration <= 180 else 45
    return WeakArea(
        title=str(raw.get("title") or raw["task_name"]).strip(),
        why=str(raw.get("why") or "").strip(),
        task_name=str(raw["task_name"]).strip(),
        category=category,
        est_duration_min=minutes,
    )


def _build_scorecard(
    payload: dict[str, Any], data: GradeInput, session_id: str, model: str
) -> Scorecard:
    titles = {c.key: c.title for c in data.rubric.criteria}
    by_key = {item["key"]: item for item in payload["criteria"]}
    criteria = [
        CriterionScore(
            key=key,
            title=titles[key],
            score=by_key[key]["score"],
            evidence=[
                Evidence(quote=q.strip(), verified=quote_in_transcript(q, data.transcript))
                for q in by_key[key].get("evidence") or []
                if isinstance(q, str) and q.strip()
            ],
            improvement=str(by_key[key].get("improvement") or "").strip(),
        )
        # Rubric order, not the model's order, so cards always read the same way.
        for key in (c.key for c in data.rubric.criteria)
    ]
    weak_areas = [w for w in map(_weak_area, payload.get("weak_areas") or []) if w]
    return Scorecard(
        id=str(uuid.uuid4()),
        session_id=session_id,
        overall_score=weighted_overall(criteria, data.rubric),
        grader_model=model,
        summary=str(payload.get("summary") or "").strip(),
        criteria=criteria,
        strengths=[
            s.strip() for s in payload.get("strengths") or [] if isinstance(s, str) and s.strip()
        ],
        weak_areas=weak_areas[:MAX_WEAK_AREAS],
    )


def grade_transcript(
    client: anthropic.Anthropic, model: str, data: GradeInput, session_id: str
) -> Scorecard:
    """Grade ``data.transcript``. Raises :class:`GradingError` on bad input or
    when no valid scorecard comes back within ``MAX_ATTEMPTS``."""
    if not data.transcript.strip():
        raise GradingError("The transcript is empty")
    if len(data.transcript) > MAX_TRANSCRIPT_CHARS:
        raise GradingError(f"Transcript is over {MAX_TRANSCRIPT_CHARS:,} characters")
    if not data.rubric.criteria:
        raise GradingError(f"Rubric {data.rubric.name!r} has no criteria")

    messages: list[dict[str, Any]] = [{"role": "user", "content": _user_message(data)}]
    problems: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=cast(Any, [SUBMIT_TOOL]),
            messages=cast(Any, messages),
        )
        tool_use = find_tool_use(response, "submit_scorecard")
        if tool_use is None:
            # Replied in prose; tool_choice can't force the tool on these models.
            problems = ["No submit_scorecard call"]
            messages += [
                {"role": "assistant", "content": response.content},
                nudge("submit_scorecard"),
            ]
            continue
        payload = dict(tool_use.input or {})
        problems = _validate(payload, data.rubric)
        if not problems:
            return _build_scorecard(payload, data, session_id, model)
        # Show the model its own card and exactly what to fix.
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "is_error": True,
                        "content": "Fix these problems and call submit_scorecard again:\n- "
                        + "\n- ".join(problems),
                    }
                ],
            }
        )
    raise GradingError("The grader did not return a valid scorecard: " + "; ".join(problems))


def weak_area_proposals(card: Scorecard) -> list[dict[str, Any]]:
    """The card's weak areas as ``propose_new_task`` proposals for the existing
    chat confirm path (``POST /api/chat/confirm``). Each carries the session
    id so the created task links back to this practice session."""
    return [
        {
            "type": "propose_new_task",
            "id": f"mock-{card.id}-{i}",
            "name": w.task_name,
            "category": w.category.value,
            "priority": Priority.P1.name,
            "est_duration_min": w.est_duration_min,
            "reason": w.why or w.title,
            "mock_session_id": card.session_id,
        }
        for i, w in enumerate(card.weak_areas)
    ]
