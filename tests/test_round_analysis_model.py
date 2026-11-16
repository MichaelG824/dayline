"""The AI-assisted round analysis against the real grader model
(``MOCK_GRADER_MODEL``, default Claude Opus 5.5), on a recorded generated
round (``tests/round_fixture.py``) with the rubric migration 016 seeds.

The card must score every criterion, end with 3-5 prioritized key points
that each cite a real moment (code checks the mm:ss against the record),
and pick up what the record makes obvious: two AI edits accepted in a few
seconds (05:44, 28:02) and an unplanned change request edit.

Opt in with ``RUN_MODEL_TESTS=1`` (needs Anthropic credentials; costs well
under a dollar).
"""

from __future__ import annotations

import os
import re

import anthropic
import pytest

from dayline.mock import grader_model, round_metrics
from dayline.mock.grader import MAX_KEY_POINTS, MIN_KEY_POINTS, GradeInput, grade
from tests.round_fixture import recorded_round, seeded_rubric

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1 to run"
)


def test_the_analysis_cites_real_moments_and_prioritizes_what_to_fix() -> None:
    problem, session, events = recorded_round()
    assert session.ended_at
    work = round_metrics.analysis_record(problem, session, events, session.ended_at)
    data = GradeInput(
        transcript="",
        rubric=seeded_rubric(),
        work=work,
        hints=problem.analysis_hints,
        key_points=True,
    )
    card = grade(anthropic.Anthropic(), grader_model(), data, session.id)

    assert [c.key for c in card.criteria] == [c.key for c in data.rubric.criteria]
    assert MIN_KEY_POINTS <= len(card.weak_areas) <= MAX_KEY_POINTS
    for point in card.weak_areas:
        moments = re.findall(r"\b\d{2}:\d{2}\b", point.why)
        assert any(m in work for m in moments), point.why
    quotes = [e for c in card.criteria for e in c.evidence]
    assert quotes and sum(e.verified for e in quotes) >= len(quotes) * 0.7, quotes
    review = next(c for c in card.criteria if c.key == "diff_review")
    assert review.score <= 2, review
    cited = " ".join(p.why for p in card.weak_areas) + " ".join(e.quote for e in review.evidence)
    assert "05:44" in cited or "28:02" in cited, cited
