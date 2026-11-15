"""Mock-interview logic: question ingest, grading, live-session work records,
and staged rounds with their interviewer.

Nothing here imports FastAPI or Supabase. Each module takes an Anthropic client
and plain domain objects, so it is testable with a fake client (see
``tests/test_mock_*.py``). The API layer (``api/services/mock.py``) wires it to
the adapters.
"""

from __future__ import annotations

import os

# Defaults are overridable per deploy without a code change.
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_GRADER_MODEL = "claude-opus-5-5"


def mock_model() -> str:
    """Model for extraction and the staged-round interviewer: fast and capable."""
    return os.environ.get("MOCK_MODEL", "").strip() or DEFAULT_MODEL


def grader_model() -> str:
    """Model for grading: runs once per session, so it can be the strongest one."""
    return os.environ.get("MOCK_GRADER_MODEL", "").strip() or DEFAULT_GRADER_MODEL
