"""Notion MCP server - stdio entrypoint (MCP SDK 2.x high-level API).

The high-level ``MCPServer`` builds each tool's JSON Schema from the function
signature, runs the initialize / tools-list / tools-call handshake, and serves
over stdio. You write the three tool functions; the SDK owns the protocol.

Each tool returns a JSON string, so any client reads one text block and parses
it - identical on the wire regardless of SDK version.

Run it against the MCP Inspector (no LLM, just a UI):

    NOTION_TOKEN=secret_xxx NOTION_DATABASE_ID=yyy \
      npx @modelcontextprotocol/inspector \
      python -m notion_mcp.server

Or, after `pip install -e mcp_server`, the console script:

    NOTION_TOKEN=... NOTION_DATABASE_ID=... notion-mcp-server
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from notion_mcp.mapping import page_to_task
from notion_mcp.notion import NotionClient
from notion_mcp.tools import CategoryLiteral, StatusLiteral

# Load mcp_server/.env if present, so NOTION_TOKEN / NOTION_DATABASE_ID don't have
# to be exported by hand. Real environment variables still take precedence.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH if _ENV_PATH.exists() else None)

mcp = MCPServer(name="notion-day-planner")

# Built lazily so importing this module (e.g. in tests) doesn't require the
# Notion env vars - they're only needed when a tool actually runs.
_notion: NotionClient | None = None


def _client() -> NotionClient:
    global _notion
    if _notion is None:
        _notion = NotionClient.from_env()
    return _notion


@mcp.tool(
    description="Return tasks from the Notion backlog, optionally filtered by "
    "status and/or category. Backs TaskSource.list_tasks()."
)
async def list_tasks(
    status: StatusLiteral | None = None,
    category: CategoryLiteral | None = None,
) -> str:
    pages = await _client().query_tasks(status=status, category=category)
    return json.dumps([page_to_task(page) for page in pages])


@mcp.tool(
    description="Return a single task by its Notion page id. "
    "Backs TaskSource.get_task()."
)
async def get_task(id: str) -> str:
    return json.dumps(page_to_task(await _client().get_page(id)))


@mcp.tool(
    description="Update a task's status and/or scheduled_time (ISO-8601 string); "
    "at least one of the two is required. Backs TaskSource.update_task()."
)
async def update_task(
    id: str,
    status: StatusLiteral | None = None,
    scheduled_time: str | None = None,
) -> str:
    if status is None and scheduled_time is None:
        raise ValueError("update_task needs at least one of: status, scheduled_time")
    page = await _client().update_task(id, status=status, scheduled_time=scheduled_time)
    return json.dumps(page_to_task(page))


def cli() -> None:
    """Console-script / module entrypoint: serve over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    cli()
