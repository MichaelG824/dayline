"""Tests for the GoogleCalendarClient timezone helpers.

These cover the genuinely tricky part - converting between the planner's naive
local datetimes and Google's RFC3339 timezone-aware strings - as pure functions,
with no Google API and no OAuth. Importing the module works without the ``google``
extra because those libraries are imported lazily inside the client.
"""

from __future__ import annotations

from datetime import datetime

from day_planner.adapters.calendar import _parse_google_dt, _to_rfc3339

TZ = "America/New_York"  # -04:00 in September (EDT)


def test_parse_timed_event_to_naive_local() -> None:
    dt = _parse_google_dt({"dateTime": "2026-09-09T09:00:00-04:00"}, TZ)
    assert dt == datetime(2026, 9, 9, 9, 0)
    assert dt.tzinfo is None  # naive, matching the planner's model


def test_parse_converts_other_offset_into_local() -> None:
    # 13:00Z is 09:00 in New York (EDT); result should be naive local 09:00.
    dt = _parse_google_dt({"dateTime": "2026-09-09T13:00:00+00:00"}, TZ)
    assert dt == datetime(2026, 9, 9, 9, 0)


def test_parse_all_day_event_returns_none() -> None:
    assert _parse_google_dt({"date": "2026-09-09"}, TZ) is None
    assert _parse_google_dt({}, TZ) is None


def test_to_rfc3339_attaches_calendar_timezone() -> None:
    s = _to_rfc3339(datetime(2026, 9, 9, 9, 0), TZ)
    assert s.startswith("2026-09-09T09:00:00")
    assert s.endswith(("-04:00", "-05:00"))  # NY offset (EDT/EST)
