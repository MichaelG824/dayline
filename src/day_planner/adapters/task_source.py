"""Task source interface + in-memory fake.

``TaskSource`` is the contract the planner uses to read and update tasks. Today
the only implementation that runs is :class:`InMemoryTaskSource`. Later, a
Notion-backed source (fronted by the captain's hand-coded MCP server) will
implement the same Protocol and drop straight into the pipeline.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Protocol, runtime_checkable

from day_planner.models import Category, Status, Task


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


class NotionTaskSource:
    """DEFERRED: real Notion-backed task source.

    This will call the captain's hand-coded Notion MCP server (tools
    ``list_tasks`` / ``get_task`` / ``update_task``) and satisfy the
    :class:`TaskSource` Protocol unchanged. It is intentionally *not* implemented
    in this increment: the MCP server does not exist yet and no credentials are
    available.

    Required when wired: ``NOTION_TOKEN`` and ``NOTION_DATABASE_ID`` (consumed by
    the MCP server, not by this client). See ``mcp_server/README.md``.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "NotionTaskSource is deferred: it depends on the captain's Notion MCP "
            "server and NOTION_TOKEN / NOTION_DATABASE_ID. Use InMemoryTaskSource "
            "until the MCP server is built. See mcp_server/README.md."
        )
