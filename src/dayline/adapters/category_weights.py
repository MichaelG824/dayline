"""Category focus ranking.

Lets the user re-rank the 5 prep categories' focus order without touching
every existing task by hand - their interview-prep focus shifts often (e.g.
"AI coding + behavioral this week"), and this is the seam that captures "what
matters most right now" independently of any one task.

``rank`` (1-5, unique) is the single source of truth for that order - not
``Priority``. Priority (P0-P3) has only 4 distinct values for 5 categories, so
it cannot represent a full 1-5 ranking without ties, and any UI letting the
user freely reorder all 5 needs a true total order to avoid silently losing
reorders (see ``supabase/migrations/004_category_rank.sql``). ``Priority`` is
still what a task actually needs, so :func:`priority_for_rank` derives one
from a category's rank only at the point of use (a new task's default
priority, or bulk-reprioritizing the backlog) - never stored as the ranking
itself.

Deliberately plain functions rather than a full Protocol + adapter pair like
``TaskSource``/``CalendarClient``: this is simple CRUD on one small table with
no scheduling logic, and it never feeds :func:`dayline.planner.core.build_plan`
directly - only the API layer reads it (see ``api/main.py``). A full Protocol
here would be the over-engineering this project otherwise avoids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from dayline.models import Category, Priority

if TYPE_CHECKING:
    from supabase import Client

# The 5 prep categories the user actually re-ranks; ERRAND/OTHER never
# participate in focus weighting (they're always plain per-task priority).
PREP_CATEGORIES: tuple[Category, ...] = (
    Category.AI_CODING_REACT_PYTHON,
    Category.AI_CODING_DSA,
    Category.BEHAVIORAL,
    Category.SYSTEM_DESIGN,
    Category.LEETCODE,
)

# Default ranking, matching the user's stated focus order (highest first).
DEFAULT_RANKS: dict[Category, int] = {
    Category.AI_CODING_REACT_PYTHON: 1,
    Category.AI_CODING_DSA: 2,
    Category.BEHAVIORAL: 3,
    Category.SYSTEM_DESIGN: 4,
    Category.LEETCODE: 5,
}

# Buckets the 5 ranks down to Priority's 4 levels for actual task use.
_RANK_TO_PRIORITY = {1: Priority.P0, 2: Priority.P0, 3: Priority.P1, 4: Priority.P1, 5: Priority.P2}


def priority_for_rank(rank: int) -> Priority:
    return _RANK_TO_PRIORITY.get(rank, Priority.P3)


def get_category_ranks(client: Client) -> dict[Category, int]:
    """Return the current category -> rank (1-5, unique) mapping.

    Falls back to :data:`DEFAULT_RANKS` for any prep category with no row yet
    (e.g. right after the migration seeds only some rows, or a fresh DB).
    """
    resp = client.table("category_weights").select("category,rank").execute()
    ranks = dict(DEFAULT_RANKS)
    for row in cast("list[dict[str, Any]]", resp.data):
        category = Category(row["category"])
        ranks[category] = int(row["rank"])
    return ranks


def set_category_ranks(client: Client, mapping: dict[Category, int]) -> None:
    """Replace the stored rank for exactly the given categories."""
    rows = [{"category": category.value, "rank": rank} for category, rank in mapping.items()]
    client.table("category_weights").upsert(rows, on_conflict="category").execute()


def get_category_weights(client: Client) -> dict[Category, Priority]:
    """Return the category -> default-priority mapping, derived from rank."""
    ranks = get_category_ranks(client)
    return {category: priority_for_rank(rank) for category, rank in ranks.items()}
