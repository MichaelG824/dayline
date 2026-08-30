# `mcp_server/` - RESERVED (captain's build)

**This directory is intentionally empty of code.**
It is reserved for the captain's own hand-coded **Notion MCP server** - the deliberate "learn MCP properly" piece of the epic (Subtask 2).
Do not scaffold server code here and do not add an MCP SDK dependency to the project; this README is a **contract only**.

## What this server will be

A standalone [Model Context Protocol](https://modelcontextprotocol.io) server that wraps the **Notion REST API** and exposes the task backlog as MCP tools.
It handles Notion authentication internally, so no MCP client ever sees a Notion token.

## Tools it must expose

The server must implement the standard MCP handshake (`initialize`, `tools/list`, `tools/call`) and expose these three tools, matching the MVP read + status/time-update surface:

| Tool | Purpose | Notes |
| --- | --- | --- |
| `list_tasks` | Return tasks, optionally filtered by `status` and/or `category`. | Backs `TaskSource.list_tasks(...)`. |
| `get_task` | Return a single task by id. | Backs `TaskSource.get_task(id)`. |
| `update_task` | Update a task's `status` and/or `scheduled_time`. | Backs `TaskSource.update_task(id, status=..., scheduled_time=...)`. |

Task creation and delete are deliberately out of scope for the MVP (see epic §4).

## How it plugs into this project

The server backs a future `NotionTaskSource` that satisfies the existing
[`adapters/task_source.py`](../src/day_planner/adapters/task_source.py) `TaskSource` Protocol.
Because the planning core and scheduler depend only on that Protocol (never on a concrete class), the Notion/MCP path drops into the pipeline **unchanged** - it simply replaces `InMemoryTaskSource`.

```
scheduler.run  ─uses→  TaskSource (Protocol)
                          ├─ InMemoryTaskSource   (runs today, no creds)
                          └─ NotionTaskSource      (this MCP server, later)
```

The field/enum contract the tools must speak is the Notion mirror of
[`models.py`](../src/day_planner/models.py): `Category`, `Priority` (P0-P3), `Status` (Backlog/Scheduled/Done), `Window` (Morning/Afternoon/Evening), plus `est_duration_min`, `fixed_time`, `preferred_window`, and `due_date`.

## Environment variables it will need

| Var | Meaning |
| --- | --- |
| `NOTION_TOKEN` | Notion internal integration token. |
| `NOTION_DATABASE_ID` | Id of the shared **Tasks** database (epic Subtask 1). |

These are consumed **inside the server**, not by the day-planner client code.

## Acceptance (from the epic's learning metrics)

A standard, off-the-shelf MCP client (not the day-planner agent) can `initialize`, `tools/list`, and `tools/call` `list_tasks` / `update_task` against this server end to end.
That interchangeability is the proof the captain built MCP, not a bespoke API.
