"""String -> enum parsers that raise ``HTTPException`` 400 on bad input.

These are an HTTP-layer concern (they translate malformed request fields into a
400), so they live beside the routers rather than in the services.
"""

from __future__ import annotations

from fastapi import HTTPException

from dayline.models import (
    Category,
    InterviewCategory,
    Priority,
    Recurrence,
    Status,
    Weekday,
    Window,
)


def parse_category(value: str) -> Category:
    try:
        return Category(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown category {value!r}") from exc


def parse_priority(value: str) -> Priority:
    try:
        return Priority[value]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown priority {value!r}") from exc


def parse_status(value: str) -> Status:
    try:
        return Status(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown status {value!r}") from exc


def parse_window(value: str) -> Window:
    try:
        return Window(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown window {value!r}") from exc


def parse_interview_category(value: str) -> InterviewCategory:
    try:
        return InterviewCategory(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unknown interview category {value!r}"
        ) from exc


def parse_recurrence(value: str) -> Recurrence:
    try:
        return Recurrence(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown recurrence {value!r}") from exc


def parse_weekday(value: str) -> Weekday:
    try:
        return Weekday(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown weekday {value!r}") from exc
