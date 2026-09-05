"""LLM chat: propose changes to today's plan, never apply them directly.

Uses the Anthropic Python SDK with a manual tool-use loop (not the SDK's tool
runner) because the propose/confirm split needs fine-grained control: the
three ``propose_*`` tools are schema-only and never executed here - their
``tool_use`` blocks are simply collected as data and returned to the caller.
Only ``list_tasks`` (read-only) is executed during a chat turn. The actual
mutation happens later, in :func:`confirm_proposals`, driven by the user's
explicit selection - never automatically because Claude "called a tool".

Requires ``ANTHROPIC_API_KEY`` in the environment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import anthropic

from dayline.adapters.task_source import TaskSource
from dayline.models import Category, Priority, Task

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are Dayline's planning assistant. You help the user reallocate \
time in their day-plan by proposing changes - you never apply changes directly.

You have a `list_tasks` tool to inspect the current day's tasks (status, \
duration, priority, category). Use it before proposing anything.

When the user asks you to reallocate time (e.g. "I'm done with work early, \
give other tasks more time"), reason about which tasks would benefit from \
more time (prefer BACKLOG tasks over DONE ones; prefer higher-priority prep \
categories) and call propose_duration_change / propose_reprioritization / \
propose_new_task as appropriate. Always include a short `reason` for each \
proposal explaining your thinking, since these are shown to the user before \
they decide whether to apply them.

Do not call propose_* tools more than necessary - group related changes into \
a single turn's proposals rather than trickling them out."""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tasks",
        "description": "List current tasks for a given day, with status, duration, priority.",
        "input_schema": {
            "type": "object",
            "properties": {"day": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["day"],
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
        "description": "Propose creating a new task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string"},
                "est_duration_min": {"type": "integer"},
                "planned_date": {"type": "string", "description": "YYYY-MM-DD or omit"},
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
]

_PROPOSE_TOOL_NAMES = {"propose_duration_change", "propose_new_task", "propose_reprioritization"}


@dataclass
class ChatTurnResult:
    explanation: str
    proposals: list[dict[str, Any]]
    history: list[dict[str, Any]]


def _list_tasks_tool_result(task_source: TaskSource, day: str) -> str:
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
            }
            for t in tasks
        ]
    )


def run_chat_turn(
    client: anthropic.Anthropic,
    task_source: TaskSource,
    day: date,
    message: str,
    history: list[dict[str, Any]] | None = None,
) -> ChatTurnResult:
    """Run one chat turn: Claude may inspect tasks (auto-executed) and emit
    proposals (never executed here). Returns Claude's explanation, the
    collected proposals, and the updated history to round-trip on the next
    call - the endpoint is stateless between HTTP requests, like the rest of
    the API."""
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": message})

    proposals: list[dict[str, Any]] = []
    response = None

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
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
            if tu.name == "list_tasks":
                day_arg = str(tu.input.get("day") or day.isoformat())
                result = _list_tasks_tool_result(task_source, day_arg)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": result}
                )
            elif tu.name in _PROPOSE_TOOL_NAMES:
                proposals.append({"type": tu.name, "id": tu.id, **tu.input})
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


def apply_proposal(task_source: TaskSource, proposal: dict[str, Any]) -> dict[str, Any]:
    """Apply one confirmed proposal via the existing TaskSource methods -
    never a separate code path from ordinary task creation/editing."""
    kind = proposal["type"]
    if kind == "propose_duration_change":
        task_source.update_task(proposal["task_id"], est_duration_min=proposal["new_duration_min"])
        return {"type": kind, "task_id": proposal["task_id"], "result": "ok"}
    if kind == "propose_new_task":
        import uuid

        task = Task(
            id=str(uuid.uuid4()),
            name=proposal["name"],
            category=Category(proposal["category"]),
            priority=Priority.P3,
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
    raise ValueError(f"Unknown proposal type {kind!r}")
