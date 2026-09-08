"""LLM chat: analysis-first planning assistant with propose/confirm mutations.

Uses the Anthropic Python SDK with a manual tool-use loop (not the SDK's tool
runner) because the propose/confirm split needs fine-grained control: every
``propose_*`` tool is schema-only and never executed here - ``tool_use`` blocks
are collected as data and returned to the caller. Only read tools
(``list_tasks``, ``get_plan``, ``list_interviews``, ``get_category_ranks``,
``get_preferences``, ``get_recent_outcomes``) auto-execute during a chat turn.
Mutations happen later in :func:`apply_proposal`, driven by the user's explicit
selection - never because Claude called a tool.

Requires ``ANTHROPIC_API_KEY`` in the environment. Never calls ``build_plan``
itself; plan snapshots come from a caller-supplied read callback.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

import anthropic

from dayline.adapters.task_source import TaskSource
from dayline.models import Category, Priority, Task

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are Dayline's analysis-first planning assistant for interview prep.

Primary job: analyze today's plan, the backlog + upcoming interviews, and recent \
outcomes/retros when data exists. Structure answers as:
1) Situation - what the day/backlog/interviews look like
2) Risks / gaps - overload, missing prep near interviews, preference mismatches
3) Recommendation - advice the user can act on

Call propose_* tools ONLY when:
- the user explicitly asks for changes (reallocate, add tasks, reprioritize, \
update preferences, nudge ranks/durations), OR
- your analysis clearly needs a concrete fix the user can confirm (e.g. an \
interview tomorrow with no matching prep on the plan).

Analysis-only turns are normal and preferred when the user is asking "how am I \
doing", "what's wrong with today", or wants a retro - return explanation with \
zero proposals.

When proposing:
- Prefer interview-proximate prep over distant work.
- Respect category focus ranks (rank 1 = highest focus).
- Prefer BACKLOG tasks over DONE ones when reallocating time.
- Do not invent P0 without a clear reason (imminent interview, user request, \
or rank-1 focus gap).
- Honor stored preferences (peak hours, category caps, standing rules like \
"mornings = DSA").
- For brain-dumps / inbox messages, emit multiple propose_new_task calls in \
one turn rather than asking the user to send one task at a time.
- Always include a short `reason` on each proposal (shown before confirm).
- Group related changes into one turn's proposals; do not trickle them.

Read tools (auto-executed): list_tasks, get_plan, list_interviews, \
get_category_ranks, get_preferences, get_recent_outcomes.
Use them before analyzing or proposing. Never claim you applied a change - \
proposals await user confirmation."""

For propose_new_task, category MUST be exactly one of these strings: \
"AI Coding - React/Python", "AI Coding - DSA", "Behavioral", "System Design", \
"Leetcode", "Errand", "Other". Never invent labels like "Interview Prep"."""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tasks",
        "description": "List current tasks with status, duration, priority, category, links.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "YYYY-MM-DD (optional filter hint)"}
            },
        },
    },
    {
        "name": "get_plan",
        "description": "Today's plan brief, scheduled blocks, and unplaced tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"day": {"type": "string", "description": "YYYY-MM-DD"}},
        },
    },
    {
        "name": "list_interviews",
        "description": "Upcoming interviews with company/role/category and linkage fields.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_category_ranks",
        "description": "Current prep-category focus order (rank 1 = highest).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_preferences",
        "description": "Stored planner preferences (peak hours, caps, standing rules).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_outcomes",
        "description": "Recent accept/reject/completion/duration-override events for retros.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max events (default 20)"}
            },
        },
    },
    {
        "name": "propose_duration_change",
        "description": "Propose changing a task's estimated duration in minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task_name": {"type": "string", "description": "human-readable, for display"},
                "new_duration_min": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["task_id", "task_name", "new_duration_min", "reason"],
        },
    },
    {
        "name": "propose_new_task",
        "description": "Propose creating a new task (emit multiple for brain-dumps); category must be an exact Category value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": [c.value for c in Category],
                    "description": "Exact Category value, e.g. Behavioral not Interview Prep",
                },
                "est_duration_min": {"type": "integer"},
                "planned_date": {"type": "string", "description": "YYYY-MM-DD or omit"},
                "priority": {
                    "type": "string",
                    "enum": ["P0", "P1", "P2", "P3"],
                    "description": "Optional; omit to use category-rank default later",
                },
                "reason": {"type": "string"},
            },
            "required": ["name", "category", "est_duration_min", "reason"],
        },
    },
    {
        "name": "propose_reprioritization",
        "description": "Propose changing a task's priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task_name": {"type": "string"},
                "new_priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                "reason": {"type": "string"},
            },
            "required": ["task_id", "task_name", "new_priority", "reason"],
        },
    },
    {
        "name": "propose_preference_update",
        "description": "Propose updating planner preferences (peak hours, caps, rules).",
        "input_schema": {
            "type": "object",
            "properties": {
                "peak_hours": {"type": "string", "description": "e.g. '9-12' or free text"},
                "category_caps": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                    "description": "category name -> max minutes/day",
                },
                "standing_rules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "e.g. ['mornings = DSA']",
                },
                "free_text": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "propose_category_rank_change",
        "description": "Propose reordering prep-category focus ranks (still needs confirm).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ranks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string"},
                            "rank": {"type": "integer"},
                        },
                        "required": ["category", "rank"],
                    },
                    "description": "Full or partial category->rank mapping (1=highest)",
                },
                "reason": {"type": "string"},
            },
            "required": ["ranks", "reason"],
        },
    },
]

_READ_TOOL_NAMES = {
    "list_tasks",
    "get_plan",
    "list_interviews",
    "get_category_ranks",
    "get_preferences",
    "get_recent_outcomes",
}

_PROPOSE_TOOL_NAMES = {
    "propose_duration_change",
    "propose_new_task",
    "propose_reprioritization",
    "propose_preference_update",
    "propose_category_rank_change",
}


@dataclass
class ChatDeps:
    """Caller-supplied read/write hooks so chat stays free of Supabase imports."""

    task_source: TaskSource
    get_plan: Callable[[date], dict[str, Any]]
    list_interviews: Callable[[], list[dict[str, Any]]]
    get_category_ranks: Callable[[], list[dict[str, Any]]]
    get_preferences: Callable[[], dict[str, Any]]
    get_recent_outcomes: Callable[[int], list[dict[str, Any]]]
    apply_preference_update: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    apply_category_ranks: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None
    # Optional snapshot injected into the system prompt every turn.
    preferences_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatTurnResult:
    explanation: str
    proposals: list[dict[str, Any]]
    history: list[dict[str, Any]]


def _list_tasks_tool_result(task_source: TaskSource) -> str:
    tasks = task_source.list_tasks()
    return json.dumps(
        [
            {
                "id": t.id,
                "name": t.name,
                "category": t.category.value,
                "priority": t.priority.name,
                "status": t.status.value,
                "estDurationMin": t.est_duration_min,
                "plannedDate": t.planned_date.isoformat() if t.planned_date else None,
                "applicationId": t.application_id,
                "interviewId": t.interview_id,
            }
            for t in tasks
        ]
    )


def _system_prompt(deps: ChatDeps) -> str:
    prefs = deps.preferences_snapshot or deps.get_preferences()
    prefs_block = json.dumps(prefs, indent=2)
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Current planner preferences (authoritative; also available via get_preferences):\n"
        f"{prefs_block}"
    )


def _execute_read_tool(name: str, tool_input: dict[str, Any], deps: ChatDeps, day: date) -> str:
    if name == "list_tasks":
        return _list_tasks_tool_result(deps.task_source)
    if name == "get_plan":
        day_arg = date.fromisoformat(str(tool_input["day"])) if tool_input.get("day") else day
        return json.dumps(deps.get_plan(day_arg))
    if name == "list_interviews":
        return json.dumps(deps.list_interviews())
    if name == "get_category_ranks":
        return json.dumps(deps.get_category_ranks())
    if name == "get_preferences":
        return json.dumps(deps.get_preferences())
    if name == "get_recent_outcomes":
        limit = int(tool_input.get("limit") or 20)
        return json.dumps(deps.get_recent_outcomes(limit))
    return json.dumps({"error": f"Unknown read tool {name!r}"})


def run_chat_turn(
    client: anthropic.Anthropic,
    deps: ChatDeps,
    day: date,
    message: str,
    history: list[dict[str, Any]] | None = None,
) -> ChatTurnResult:
    """Run one chat turn: read tools auto-execute; propose tools are collected only.

    Returns Claude's explanation, collected proposals (may be empty after pure
    analysis), and updated history to round-trip on the next call.
    """
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": message})

    proposals: list[dict[str, Any]] = []
    response = None
    system = _system_prompt(deps)

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=cast(Any, TOOLS),
            messages=cast(Any, messages),
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            break

        tool_results: list[dict[str, Any]] = []
        stop_loop = False
        for tu in tool_uses:
            if tu.name in _READ_TOOL_NAMES:
                result = _execute_read_tool(tu.name, dict(tu.input or {}), deps, day)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": result}
                )
            elif tu.name in _PROPOSE_TOOL_NAMES:
                proposals.append({"type": tu.name, "id": tu.id, **dict(tu.input or {})})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": "Proposal recorded, awaiting user confirmation.",
                    }
                )
                stop_loop = True
            else:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": f"Unknown tool {tu.name!r}",
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})
        if stop_loop:
            break

    explanation = next((b.text for b in response.content if b.type == "text"), "")
    return ChatTurnResult(explanation=explanation, proposals=proposals, history=messages)


# Common LLM slips -> real Category values. Exact enum values still win first.
_CATEGORY_ALIASES: dict[str, Category] = {
    "interview prep": Category.BEHAVIORAL,
    "behavioral interview": Category.BEHAVIORAL,
    "behavioral prep": Category.BEHAVIORAL,
    "system design prep": Category.SYSTEM_DESIGN,
    "leetcode prep": Category.LEETCODE,
    "dsa": Category.LEETCODE,
    "ai coding": Category.AI_CODING_REACT_PYTHON,
    "react": Category.AI_CODING_REACT_PYTHON,
    "errands": Category.ERRAND,
}


def parse_category(raw: str) -> Category:
    """Resolve a proposal category string to :class:`Category`.

    Accepts exact enum values, case-insensitive matches, and a small alias map
    for labels models invent (e.g. \"Interview Prep\" -> Behavioral).
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("category is required")
    try:
        return Category(text)
    except ValueError:
        pass
    key = text.lower()
    for cat in Category:
        if cat.value.lower() == key or cat.name.lower() == key.replace(" ", "_").replace("-", "_"):
            return cat
    alias = _CATEGORY_ALIASES.get(key)
    if alias is not None:
        return alias
    allowed = ", ".join(repr(c.value) for c in Category)
    raise ValueError(f"Unknown category {raw!r}; use one of: {allowed}")


def apply_proposal(deps: ChatDeps, proposal: dict[str, Any]) -> dict[str, Any]:
    """Apply one confirmed proposal via existing TaskSource / preference hooks.

    Never a separate mutation path from ordinary task creation/editing.
    """
    kind = proposal["type"]
    task_source = deps.task_source
    if kind == "propose_duration_change":
        task_source.update_task(proposal["task_id"], est_duration_min=proposal["new_duration_min"])
        return {"type": kind, "task_id": proposal["task_id"], "result": "ok"}
    if kind == "propose_new_task":
        import uuid

        priority = (
            Priority[proposal["priority"]]
            if proposal.get("priority") in {"P0", "P1", "P2", "P3"}
            else Priority.P3
        )
        task = Task(
            id=str(uuid.uuid4()),
            name=proposal["name"],
            category=parse_category(str(proposal["category"])),
            priority=priority,
            est_duration_min=proposal["est_duration_min"],
            planned_date=date.fromisoformat(proposal["planned_date"])
            if proposal.get("planned_date")
            else None,
        )
        created = task_source.create_task(task)
        return {"type": kind, "task_id": created.id, "result": "ok"}
    if kind == "propose_reprioritization":
        task_source.update_task(proposal["task_id"], priority=Priority[proposal["new_priority"]])
        return {"type": kind, "task_id": proposal["task_id"], "result": "ok"}
    if kind == "propose_preference_update":
        if deps.apply_preference_update is None:
            raise ValueError("Preference updates are not configured")
        raw_patch: dict[str, Any] = {
            "peakHours": proposal.get("peak_hours"),
            "categoryCaps": proposal.get("category_caps"),
            "standingRules": proposal.get("standing_rules"),
            "freeText": proposal.get("free_text"),
        }
        # Drop keys the model omitted so patch merges cleanly.
        patch = {k: v for k, v in raw_patch.items() if v is not None}
        prefs_updated = deps.apply_preference_update(patch)
        return {"type": kind, "result": "ok", "preferences": prefs_updated}
    if kind == "propose_category_rank_change":
        if deps.apply_category_ranks is None:
            raise ValueError("Category rank updates are not configured")
        ranks = list(proposal.get("ranks") or [])
        ranks_updated = deps.apply_category_ranks(ranks)
        return {"type": kind, "result": "ok", "ranks": ranks_updated}
    raise ValueError(f"Unknown proposal type {kind!r}")
