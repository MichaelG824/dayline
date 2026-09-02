"""Thin async client for the Notion REST API.

This layer is pure transport: it makes HTTP calls and returns raw Notion JSON.
It holds the token (read from the environment) and knows nothing about MCP - so
you could reuse it from a plain script while learning the Notion API first.

Schema knowledge (column names, filter/update shapes) lives in ``mapping.py``.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from notion_mcp.mapping import build_filter, build_update_properties

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"  # Notion pins behavior to a dated version


def _raise_readable(resp: httpx.Response) -> None:
    """Raise a readable ValueError on a Notion HTTP error instead of an opaque
    ``httpx.HTTPStatusError`` (bad db id, wrong column, expired token)."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        first_line = resp.text.splitlines()[0] if resp.text else ""
        raise ValueError(f"Notion API error {resp.status_code}: {first_line}") from exc


class NotionClient:
    """Talks to one Notion database. Construct via :meth:`from_env`."""

    def __init__(self, token: str, database_id: str) -> None:
        self._database_id = database_id
        # Sent on every request. The token lives HERE, inside the server - no
        # MCP client ever sees it. That is the security point of the MCP layer.
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    @classmethod
    def from_env(cls) -> NotionClient:
        """Read NOTION_TOKEN and NOTION_DATABASE_ID from the environment."""
        try:
            token = os.environ["NOTION_TOKEN"]
            database_id = os.environ["NOTION_DATABASE_ID"]
        except KeyError as exc:
            raise RuntimeError(
                f"Missing required environment variable: {exc}. "
                "Set NOTION_TOKEN and NOTION_DATABASE_ID."
            ) from exc
        return cls(token, database_id)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=NOTION_API, headers=self._headers, timeout=30)

    async def query_tasks(
        self, status: str | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        """Query the database, following pagination, return raw page objects."""
        body: dict[str, Any] = {}
        filt = build_filter(status, category)
        if filt is not None:
            body["filter"] = filt

        pages: list[dict[str, Any]] = []
        async with self._client() as client:
            payload = dict(body)
            while True:
                resp = await client.post(
                    f"/databases/{self._database_id}/query", json=payload
                )
                _raise_readable(resp)
                data = resp.json()
                pages.extend(data["results"])
                # Notion returns one page of results at a time; ask for the next.
                if not data.get("has_more"):
                    break
                payload = dict(body, start_cursor=data["next_cursor"])
        return pages

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """Fetch a single page (task) by id."""
        async with self._client() as client:
            resp = await client.get(f"/pages/{page_id}")
            _raise_readable(resp)
            return resp.json()

    async def update_task(
        self,
        page_id: str,
        status: str | None = None,
        scheduled_time: str | None = None,
    ) -> dict[str, Any]:
        """Patch a page's status and/or scheduled_time; return the updated page."""
        properties = build_update_properties(status, scheduled_time)
        async with self._client() as client:
            resp = await client.patch(
                f"/pages/{page_id}", json={"properties": properties}
            )
            _raise_readable(resp)
            return resp.json()  # PATCH returns the full updated page
