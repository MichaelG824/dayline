"""Planner preference memory (peak hours, category caps, standing rules).

Plain functions over one small table, same shape as ``category_weights`` -
simple CRUD that never feeds ``build_plan``, so a full Protocol would be
over-engineering. Injected into the chat system prompt / ``get_preferences``
tool every turn; mutations go through propose/confirm only.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from supabase import Client

PREFERENCE_ROW_ID = "default"


@dataclass
class PlannerPreferences:
    """Structured prefs plus optional free-text standing rules."""

    peak_hours: str | None = None
    category_caps: dict[str, int] = field(default_factory=dict)
    standing_rules: list[str] = field(default_factory=list)
    free_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "peakHours": self.peak_hours,
            "categoryCaps": dict(self.category_caps),
            "standingRules": list(self.standing_rules),
            "freeText": self.free_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlannerPreferences:
        if not data:
            return cls()
        caps_raw = data.get("categoryCaps") or data.get("category_caps") or {}
        rules_raw = data.get("standingRules") or data.get("standing_rules") or []
        return cls(
            peak_hours=data.get("peakHours") or data.get("peak_hours"),
            category_caps={str(k): int(v) for k, v in dict(caps_raw).items()},
            standing_rules=[str(r) for r in list(rules_raw)],
            free_text=data.get("freeText") or data.get("free_text"),
        )


class InMemoryPreferencesStore:
    """Test/local prefs store - no network."""

    def __init__(self, initial: PlannerPreferences | None = None) -> None:
        self._prefs = initial or PlannerPreferences()

    def get_preferences(self) -> PlannerPreferences:
        return deepcopy(self._prefs)

    def set_preferences(self, prefs: PlannerPreferences) -> PlannerPreferences:
        self._prefs = deepcopy(prefs)
        return self.get_preferences()

    def patch_preferences(self, patch: dict[str, Any]) -> PlannerPreferences:
        current = self.get_preferences().to_dict()
        merged = {**current, **{k: v for k, v in patch.items() if v is not None}}
        if "standingRules" in patch and patch["standingRules"] is None:
            merged["standingRules"] = []
        if "categoryCaps" in patch and patch["categoryCaps"] is None:
            merged["categoryCaps"] = {}
        return self.set_preferences(PlannerPreferences.from_dict(merged))


def get_preferences(client: Client) -> PlannerPreferences:
    """Load the single prefs row, or empty defaults if missing."""
    resp = (
        client.table("planner_preferences")
        .select("preferences,free_text")
        .eq("id", PREFERENCE_ROW_ID)
        .limit(1)
        .execute()
    )
    rows = cast("list[dict[str, Any]]", resp.data or [])
    if not rows:
        return PlannerPreferences()
    row = rows[0]
    data = dict(row.get("preferences") or {})
    if row.get("free_text") is not None:
        data["freeText"] = row["free_text"]
    return PlannerPreferences.from_dict(data)


def set_preferences(client: Client, prefs: PlannerPreferences) -> PlannerPreferences:
    """Upsert the single prefs row."""
    payload = {
        "id": PREFERENCE_ROW_ID,
        "preferences": {
            "peakHours": prefs.peak_hours,
            "categoryCaps": prefs.category_caps,
            "standingRules": prefs.standing_rules,
        },
        "free_text": prefs.free_text,
    }
    client.table("planner_preferences").upsert(payload, on_conflict="id").execute()
    return get_preferences(client)


def patch_preferences(client: Client, patch: dict[str, Any]) -> PlannerPreferences:
    """Merge a partial patch into stored prefs and save."""
    current = get_preferences(client).to_dict()
    merged = {**current}
    if "peakHours" in patch or "peak_hours" in patch:
        merged["peakHours"] = patch.get("peakHours", patch.get("peak_hours"))
    if "categoryCaps" in patch or "category_caps" in patch:
        caps = patch.get("categoryCaps", patch.get("category_caps"))
        merged["categoryCaps"] = caps if caps is not None else {}
    if "standingRules" in patch or "standing_rules" in patch:
        rules = patch.get("standingRules", patch.get("standing_rules"))
        merged["standingRules"] = rules if rules is not None else []
    if "freeText" in patch or "free_text" in patch:
        merged["freeText"] = patch.get("freeText", patch.get("free_text"))
    return set_preferences(client, PlannerPreferences.from_dict(merged))
