"""Translation between Notion pages and the day-planner task shape.

This is the ONE file that knows your Notion database's schema. Everything else
(the transport in ``notion.py``, the wiring in ``server.py``) stays generic.

This mapping is tuned to the "Task Manager" database, whose vocabulary differs
from the planner's, so the adapter translates both ways:

* Column names:  Notion ``Task`` -> ``name``,  Notion ``Due`` -> ``due_date``.
* ``Status`` is Notion's dedicated *status* property type (not a select), and
  its options are ``Todo / In progress / Done`` -> ``Backlog / Scheduled / Done``.
* ``Priority`` is a select with ``Low / Medium / High`` -> ``P2 / P1 / P0``.
"""

from __future__ import annotations

from typing import Any

# --- Your Notion column names -------------------------------------------------
PROP_NAME = "Task"                       # Title
PROP_CATEGORY = "Category"               # Select
PROP_PRIORITY = "Priority"               # Select  (Low / Medium / High)
PROP_STATUS = "Status"                   # Status  (Todo / In progress / Done)
PROP_DURATION = "Est Duration Min"       # Number
PROP_FIXED_TIME = "Fixed Time"           # Date
PROP_PREFERRED_WINDOW = "Preferred Window"  # Select
PROP_DUE_DATE = "Due"                    # Date
PROP_SCHEDULED_TIME = "Scheduled Time"   # Date (written by update_task)
PROP_RECURS = "Recurs"                   # Select (Daily / Weekdays / Weekly)
PROP_RECUR_DAY = "Recur Day"             # Select (Mon..Sun; used when Recurs=Weekly)

# --- Value translation --------------------------------------------------------
# The planner speaks Backlog/Scheduled/Done and P0..P3; Notion speaks its own
# option names. These tables are the single source of truth for both directions.
STATUS_FROM_NOTION = {"Todo": "Backlog", "In progress": "Scheduled", "Done": "Done"}
STATUS_TO_NOTION = {v: k for k, v in STATUS_FROM_NOTION.items()}

# Notion Priority (3 levels) -> planner Priority (P0 highest). Read-only: the
# planner never writes priority back, so no reverse table is needed.
PRIORITY_FROM_NOTION = {"High": "P0", "Medium": "P1", "Low": "P2"}


# --- Readers: crack open one Notion property envelope each --------------------
def _title(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    parts = prop.get("title", [])
    return parts[0]["plain_text"] if parts else ""


def _select(prop: dict[str, Any] | None) -> str | None:
    if not prop or prop.get("select") is None:
        return None
    return prop["select"]["name"]


def _status(prop: dict[str, Any] | None) -> str | None:
    """Read Notion's dedicated *status* property type (distinct from select)."""
    if not prop or prop.get("status") is None:
        return None
    return prop["status"]["name"]


def _number(prop: dict[str, Any] | None) -> float | None:
    if not prop:
        return None
    return prop.get("number")


def _date(prop: dict[str, Any] | None) -> str | None:
    if not prop or prop.get("date") is None:
        return None
    return prop["date"]["start"]  # ISO-8601 string, e.g. "2026-09-01T09:00:00"


# --- Read: Notion page -> task dict ------------------------------------------
def page_to_task(page: dict[str, Any]) -> dict[str, Any]:
    """Flatten one Notion page into the planner's task contract.

    Status and priority values are translated into the planner's vocabulary.
    Dates come back as ISO strings; the day-planner client parses them into
    ``datetime`` when it rebuilds a ``Task``.
    """
    props = page.get("properties", {})
    notion_status = _status(props.get(PROP_STATUS))
    notion_priority = _select(props.get(PROP_PRIORITY))
    return {
        "id": page["id"],
        "name": _title(props.get(PROP_NAME)),
        "category": _select(props.get(PROP_CATEGORY)),
        "priority": PRIORITY_FROM_NOTION.get(notion_priority) if notion_priority else None,
        "status": STATUS_FROM_NOTION.get(notion_status, notion_status),
        "est_duration_min": _number(props.get(PROP_DURATION)),
        "fixed_time": _date(props.get(PROP_FIXED_TIME)),
        "preferred_window": _select(props.get(PROP_PREFERRED_WINDOW)),
        "due_date": _date(props.get(PROP_DUE_DATE)),
        "recurs": _select(props.get(PROP_RECURS)),
        "recur_day": _select(props.get(PROP_RECUR_DAY)),
    }


# --- Write helpers: build Notion request bodies -------------------------------
def build_filter(status: str | None, category: str | None) -> dict[str, Any] | None:
    """Turn our two optional args into Notion's query filter grammar.

    Note ``Status`` filters on the *status* property type (not select) and maps
    the planner value to the Notion option name.
    """
    clauses: list[dict[str, Any]] = []
    if status is not None:
        notion_status = STATUS_TO_NOTION.get(status, status)
        clauses.append({"property": PROP_STATUS, "status": {"equals": notion_status}})
    if category is not None:
        clauses.append({"property": PROP_CATEGORY, "select": {"equals": category}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"and": clauses}


def build_update_properties(
    status: str | None, scheduled_time: str | None
) -> dict[str, Any]:
    """Build the ``properties`` body for a Notion page PATCH.

    Only the fields you pass are included, so an update touches nothing else.
    """
    properties: dict[str, Any] = {}
    if status is not None:
        notion_status = STATUS_TO_NOTION.get(status, status)
        properties[PROP_STATUS] = {"status": {"name": notion_status}}
    if scheduled_time is not None:
        properties[PROP_SCHEDULED_TIME] = {"date": {"start": scheduled_time}}
    return properties
