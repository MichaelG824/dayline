# Running the Notion MCP server

A standalone MCP server exposing the Notion task backlog as three tools:
`list_tasks`, `get_task`, `update_task`. It backs the day-planner `TaskSource`.

## Shape

```
mcp_server/
  pyproject.toml            # own project - keeps the MCP SDK out of day-planner
  .env.example              # NOTION_TOKEN / NOTION_DATABASE_ID
  src/notion_mcp/
    tools.py                # the 3 tool schemas (what a client sees)
    notion.py               # async Notion REST client (holds the token)
    mapping.py              # Notion page <-> task shape; column names live here
    server.py               # list_tools + call_tool handlers, stdio entrypoint
```

Request flow for one call:

```
client --initialize-->            (MCP SDK handles the handshake)
client --tools/list-->  list_tools()  -> the 3 schemas
client --tools/call-->  call_tool()   -> notion.py -> Notion REST -> mapping -> JSON
```

## Install

```
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'         # run from inside mcp_server/
```

## Credentials

Copy `.env.example` to `.env` and fill in `NOTION_TOKEN` and
`NOTION_DATABASE_ID`. The server auto-loads `mcp_server/.env` at startup, so you
do not need to export them by hand (real environment variables still win over
the file). The integration must be connected to the database in Notion:
open the database → ••• → Connections → add your integration.

## Try it with the MCP Inspector (no LLM, just a UI)

```
npx @modelcontextprotocol/inspector python -m notion_mcp.server
```

(Or override the file for a one-off:
`NOTION_TOKEN=... NOTION_DATABASE_ID=... npx @modelcontextprotocol/inspector python -m notion_mcp.server`.)

Then in the Inspector: connect, open **Tools**, and call `list_tasks` with
`{"status": "Backlog"}`. Seeing your tasks come back as JSON is the acceptance
proof that this is real, off-the-shelf-usable MCP.

## Before it works against real data

Match `mapping.py` to your Notion "Tasks" database:

1. The `PROP_*` column-name constants must equal your Notion headers exactly.
2. The assumed property types (Select / Number / Date / Title) must match how
   you modeled each column.

## Wiring into day-planner (later)

Implement `NotionTaskSource` in
`src/day_planner/adapters/task_source.py`. It acts as an MCP *client*: it spawns
this server over stdio (MCP SDK `ClientSession`), calls these tools, and maps the
JSON back into `Task` objects. The planner core is unchanged.
