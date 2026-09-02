"""Shared tool vocabulary.

With the MCP SDK 2.x high-level ``MCPServer``, each tool's JSON Schema is built
from the function signature in ``server.py`` - so the enums live here as
``Literal`` type aliases (mirrors of the day-planner ``models.py``) that the
handlers annotate their parameters with.
"""

from __future__ import annotations

from typing import Literal

# Mirror of models.Status.
StatusLiteral = Literal["Backlog", "Scheduled", "Done"]

# Mirror of models.Category.
CategoryLiteral = Literal[
    "Behavioral", "AI Coding", "Leetcode", "System Design", "Errand", "Other"
]
