"""The in-session assistant against the real model (the default, Claude
Sonnet 4.5, or ``MOCK_ASSISTANT_MODEL``): an ask turn reads the code and
proposes nothing, and an edit turn drafts the fix as a reviewable edit.

Opt in with ``RUN_MODEL_TESTS=1`` (needs Anthropic credentials; costs a few
cents).
"""

from __future__ import annotations

import os
from typing import Any

import anthropic
import pytest

from dayline.mock import assistant_model
from dayline.mock.assistant import ToolError, TurnResult, Workspace, stream_turn

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1 to run"
)

FILES = {
    "README.md": "# Calculator\n\n`add` in calc.py returns the wrong answer. Fix it.\n",
    "calc.py": "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
}


def _workspace() -> Workspace:
    def read(path: str) -> dict[str, Any]:
        if path not in FILES:
            raise ToolError(f"No file {path!r}")
        return {"content": FILES[path], "version": "v1"}

    return Workspace(
        list_files=lambda: [{"path": p, "size": len(c)} for p, c in sorted(FILES.items())],
        read_file=read,
        snapshot=lambda: dict(FILES),
        test_report=lambda: None,
        commands=lambda: [],
    )


def _run(mode: str, prompt: str) -> TurnResult:
    events = list(
        stream_turn(anthropic.Anthropic(), assistant_model(), mode, [], prompt, _workspace())  # type: ignore[arg-type]
    )
    kind, result = events[-1]
    assert kind == "result"
    assert isinstance(result, TurnResult)
    assert "".join(v for k, v in events if k == "delta").strip() == result.text
    return result


def test_ask_reads_the_code_and_proposes_nothing() -> None:
    result = _run("ask", "What does add in calc.py return for add(2, 3)?")
    assert result.status == "done"
    assert any(t.startswith("read calc.py") for t in result.tools), result.tools
    assert result.proposals == []
    assert "-1" in result.text


def test_edit_drafts_the_fix_as_a_reviewable_edit() -> None:
    result = _run("edit", "Fix add in calc.py.")
    assert result.status == "done"
    (proposal,) = result.proposals
    assert proposal.path == "calc.py" and proposal.base_version == "v1"
    assert "return a + b" in proposal.content
    # Only add changed; sub still subtracts.
    assert proposal.content.count("return a - b") == 1
    assert proposal.counts() == (1, 1)
