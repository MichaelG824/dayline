"""Task source interface + in-memory fake.

``TaskSource`` is the contract the planner uses to read and update tasks. Today
the only implementation that runs is :class:`InMemoryTaskSource`. Later, a
Notion-backed source (fronted by the captain's hand-coded MCP server) will
implement the same Protocol and drop straight into the pipeline.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypeVar, runtime_checkable

from day_planner.models import (
    Category,
    Priority,
    Recurrence,
    Status,
    Task,
    Weekday,
    Window,
)


@runtime_checkable
class TaskSource(Protocol):
    """Read/update surface over the task backlog.

    Kept intentionally small (read + status/time update) to match the MVP MCP
    tool surface: ``list_tasks``, ``get_task``, ``update_task``.
    """

    def list_tasks(
        self,
        *,
        status: Status | None = None,
        category: Category | None = None,
    ) -> list[Task]:
        """Return tasks, optionally filtered by status and/or category."""
        ...

    def get_task(self, task_id: str) -> Task:
        """Return a single task by id. Raises ``KeyError`` if absent."""
        ...

    def update_task(
        self,
        task_id: str,
        *,
        status: Status | None = None,
        scheduled_time: datetime | None = None,
    ) -> Task:
        """Update a task's status and/or scheduled time; return the new state."""
        ...


class InMemoryTaskSource:
    """A fully working in-memory :class:`TaskSource` for tests, local runs, and
    the Streamlit dashboard - no network, no credentials.

    Copies are returned on read so callers can't mutate internal state by
    accident (mirrors the isolation a real API boundary gives you).
    """

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        # scheduled_time is not a field on Task; the real Notion schema stores it
        # separately, so the fake tracks it on the side too.
        self._scheduled_time: dict[str, datetime] = {}
        for task in tasks or []:
            self._tasks[task.id] = copy.deepcopy(task)

    def list_tasks(
        self,
        *,
        status: Status | None = None,
        category: Category | None = None,
    ) -> list[Task]:
        result = [
            copy.deepcopy(t)
            for t in self._tasks.values()
            if (status is None or t.status == status)
            and (category is None or t.category == category)
        ]
        # Stable order for deterministic downstream behavior.
        result.sort(key=lambda t: t.id)
        return result

    def get_task(self, task_id: str) -> Task:
        return copy.deepcopy(self._tasks[task_id])

    def update_task(
        self,
        task_id: str,
        *,
        status: Status | None = None,
        scheduled_time: datetime | None = None,
    ) -> Task:
        task = self._tasks[task_id]  # KeyError if unknown, matching the contract
        if status is not None:
            task.status = status
        if scheduled_time is not None:
            self._scheduled_time[task_id] = scheduled_time
        return copy.deepcopy(task)

    # Convenience for tests/UI - not part of the Protocol.
    def scheduled_time_of(self, task_id: str) -> datetime | None:
        """Return the last scheduled time recorded for a task, if any."""
        return self._scheduled_time.get(task_id)


# Fallback duration (minutes) for a Notion row with no duration set, so such a
# task can still be scheduled instead of failing Task construction.
DEFAULT_DURATION_MIN = 30


class NotionTaskSource:
    """Real Notion-backed :class:`TaskSource`, fronted by the hand-coded MCP server.

    Acts as an MCP *client*: it launches the Notion MCP server over stdio, calls
    its ``list_tasks`` / ``get_task`` / ``update_task`` tools, and maps the JSON
    results into :class:`Task` objects. The planner core and scheduler use it
    through the :class:`TaskSource` Protocol, unchanged.

    Needs the ``notion`` extra (the MCP client SDK): ``pip install '.[notion]'``.
    The server itself reads ``NOTION_TOKEN`` / ``NOTION_DATABASE_ID`` from
    ``mcp_server/.env``; this client never sees the token.

    By default it launches ``python -m notion_mcp.server`` from the ``mcp_server``
    directory, preferring that sub-project's ``.venv`` interpreter. Override
    ``command`` / ``args`` / ``cwd`` / ``env`` for a different layout.
    """

    def __init__(
        self,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        # Lazy import so this module still imports without the MCP SDK (e.g. in
        # tests that only use InMemoryTaskSource).
        try:
            from mcp import StdioServerParameters
        except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "NotionTaskSource needs the MCP client SDK. Install the extra: "
                "pip install '.[notion]'."
            ) from exc

        server_dir = (
            Path(cwd) if cwd else Path(__file__).resolve().parents[3] / "mcp_server"
        )
        if command is None:
            venv_python = server_dir / ".venv" / "bin" / "python"
            command = str(venv_python) if venv_python.exists() else sys.executable

        run_env = dict(os.environ)
        src_path = str(server_dir / "src")
        existing = run_env.get("PYTHONPATH")
        run_env["PYTHONPATH"] = (
            src_path if not existing else f"{src_path}{os.pathsep}{existing}"
        )
        if env:
            run_env.update(env)

        self._params = StdioServerParameters(
            command=command,
            args=args or ["-m", "notion_mcp.server"],
            cwd=str(server_dir),
            env=run_env,
        )

    # --- TaskSource Protocol -------------------------------------------------
    def list_tasks(
        self,
        *,
        status: Status | None = None,
        category: Category | None = None,
    ) -> list[Task]:
        args: dict[str, str] = {}
        if status is not None:
            args["status"] = status.value
        if category is not None:
            args["category"] = category.value
        data = self._call("list_tasks", args)
        return [_dict_to_task(d) for d in data]

    def get_task(self, task_id: str) -> Task:
        return _dict_to_task(self._call("get_task", {"id": task_id}))

    def update_task(
        self,
        task_id: str,
        *,
        status: Status | None = None,
        scheduled_time: datetime | None = None,
    ) -> Task:
        args: dict[str, str] = {"id": task_id}
        if status is not None:
            args["status"] = status.value
        if scheduled_time is not None:
            args["scheduled_time"] = scheduled_time.isoformat()
        return _dict_to_task(self._call("update_task", args))

    # --- MCP plumbing --------------------------------------------------------
    def _call(self, tool: str, arguments: dict[str, str]) -> Any:
        """Run one tool call against a fresh server session; return parsed JSON.

        A new stdio session per call keeps this dead-simple (no connection
        lifecycle to manage) - fine for a single-user, once-a-day planner.
        """
        return asyncio.run(self._call_async(tool, arguments))

    async def _call_async(self, tool: str, arguments: dict[str, str]) -> Any:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(self._params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)

        text = result.content[0].text if result.content else "null"
        # MCP SDK 2.x renamed ``isError`` -> ``is_error``; tolerate both.
        is_error = getattr(result, "is_error", getattr(result, "isError", False))
        if is_error:
            raise RuntimeError(f"MCP tool {tool!r} failed: {text}")
        return json.loads(text)


# --------------------------------------------------------------------------- #
# JSON (from the MCP server) -> domain Task
# --------------------------------------------------------------------------- #
_E = TypeVar("_E", bound=Enum)


def _dict_to_task(d: dict[str, Any]) -> Task:
    """Map a task dict from the MCP server into a domain :class:`Task`.

    Unknown enum values and missing fields degrade to safe defaults rather than
    raising, so one malformed Notion row can't break a whole plan.
    """
    duration = d.get("est_duration_min")
    return Task(
        id=d["id"],
        name=d.get("name") or "(untitled)",
        category=_opt_enum(Category, d.get("category")) or Category.OTHER,
        priority=_priority(d.get("priority")),
        est_duration_min=int(duration) if duration else DEFAULT_DURATION_MIN,
        status=_opt_enum(Status, d.get("status")) or Status.BACKLOG,
        fixed_time=_parse_dt(d.get("fixed_time")),
        preferred_window=_opt_enum(Window, d.get("preferred_window")),
        due_date=_parse_dt(d.get("due_date")),
        recurs=_opt_enum(Recurrence, d.get("recurs")),
        recur_day=_opt_enum(Weekday, d.get("recur_day")),
    )


def _opt_enum(enum_cls: type[_E], value: Any) -> _E | None:
    """Coerce ``value`` into ``enum_cls`` by value, or ``None`` if unknown."""
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _priority(value: Any) -> Priority:
    """Notion priority arrives as a name ('P0'..'P3'); default to lowest."""
    if not value:
        return Priority.P3
    try:
        return Priority[value]
    except KeyError:
        return Priority.P3


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
