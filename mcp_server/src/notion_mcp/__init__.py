"""Standalone Notion MCP server for the day-planner.

Exposes the Notion task backlog as three MCP tools - ``list_tasks``,
``get_task``, ``update_task`` - matching the day-planner ``TaskSource`` Protocol.
The Notion token lives entirely inside this server; no MCP client ever sees it.
"""
