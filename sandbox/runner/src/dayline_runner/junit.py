"""Parse JUnit XML (pytest, vitest, surefire, go-junit-report, ...) into one
test report shape.

The XML comes out of the sandbox, so treat it as untrusted: callers cap its
size before parsing, and the report caps case count and message length.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Outcome = Literal["passed", "failed", "error", "skipped"]
Status = Literal["passed", "failed", "error", "timeout"]

MAX_CASES = 500
MAX_MESSAGE_CHARS = 4000
MAX_OUTPUT_CHARS = 20_000


@dataclass(slots=True)
class TestCase:
    name: str
    classname: str
    outcome: Outcome
    message: str = ""
    duration_s: float = 0.0


@dataclass(slots=True)
class TestReport:
    """One test run. ``status`` is the headline: ``error`` means the tests
    could not run (no results, or nothing collected), not that one failed."""

    status: Status
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    exit_code: int | None = None
    output: str = ""
    cases: list[TestCase] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["cases"] = [asdict(c) for c in self.cases]
        return data


def _float(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _case(element: ET.Element) -> TestCase:
    outcome: Outcome = "passed"
    message = ""
    for tag in ("failure", "error", "skipped"):
        child = element.find(tag)
        if child is None:
            continue
        outcome = "failed" if tag == "failure" else "error" if tag == "error" else "skipped"
        text = (child.get("message") or "").strip()
        body = (child.text or "").strip()
        # The body is usually the traceback; prefer it when the attribute is a
        # one-line summary that the body already contains.
        message = body if body and (not text or text in body) else text or body
        break
    return TestCase(
        name=element.get("name") or "(unnamed)",
        classname=element.get("classname") or "",
        outcome=outcome,
        message=message[:MAX_MESSAGE_CHARS],
        duration_s=round(_float(element.get("time")), 3),
    )


def tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """The end of ``text`` (where test failures are summarised), marked when cut."""
    if len(text) <= limit:
        return text
    return "…(earlier output cut)\n" + text[-limit:]


def parse_junit(xml: bytes) -> list[TestCase]:
    """Every ``<testcase>`` in the document. Raises ``ValueError`` on bad XML."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"Unreadable JUnit XML: {exc}") from exc
    return [_case(e) for e in root.iter("testcase")]


def build_report(
    cases: list[TestCase] | None,
    *,
    exit_code: int | None,
    output: str,
    duration_s: float,
    timed_out: bool,
) -> TestReport:
    """Summarise a run. ``cases`` is ``None`` when no JUnit XML was produced."""
    found = cases or []
    counts = {o: sum(1 for c in found if c.outcome == o) for o in ("passed", "failed", "error")}
    status: Status
    if timed_out:
        status = "timeout"
    elif not found:
        status = "error"
    elif counts["failed"] or counts["error"]:
        status = "failed"
    else:
        status = "passed"
    return TestReport(
        status=status,
        passed=counts["passed"],
        failed=counts["failed"],
        errors=counts["error"],
        skipped=sum(1 for c in found if c.outcome == "skipped"),
        duration_s=round(duration_s, 2),
        exit_code=exit_code,
        output=tail(output),
        # Failures first so a capped list never hides them.
        cases=sorted(found, key=lambda c: c.outcome == "passed")[:MAX_CASES],
    )
