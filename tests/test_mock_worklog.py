"""Work record: diffs, line counts, and the timeline the grader reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dayline.mock.worklog import line_changes, repo_diff, timeline, work_record
from dayline.models import MockEvent, MockEventKind, MockSession, MockSessionKind

START = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _event(kind: MockEventKind, seconds: int, **data: object) -> MockEvent:
    return MockEvent(
        session_id="s1", kind=kind, data=dict(data), at=START + timedelta(seconds=seconds)
    )


def test_repo_diff_covers_changed_added_and_deleted_files() -> None:
    diff = repo_diff(
        {"a.py": "x = 1\n", "gone.py": "y = 2", "same.py": "z\n"},
        {"a.py": "x = 2\n", "new.py": "w = 3\n", "same.py": "z\n"},
    )
    assert "--- a/a.py\n+++ b/a.py" in diff and "-x = 1\n+x = 2\n" in diff
    assert "--- /dev/null\n+++ b/new.py" in diff
    # The deleted file had no trailing newline; it must not run into the next header.
    assert "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-y = 2\n" in diff
    assert "same.py" not in diff


def test_line_changes() -> None:
    assert line_changes("a\nb\nc", "a\nB\nc\nd") == (2, 1)
    assert line_changes(None, "a\nb") == (2, 0)


def test_back_to_back_saves_of_one_file_merge() -> None:
    lines = timeline(
        [
            _event(MockEventKind.SESSION_STARTED, 0),
            _event(MockEventKind.FILE_SAVED, 65, path="a.py", added=2, removed=1),
            _event(MockEventKind.FILE_SAVED, 70, path="a.py", added=1, removed=0),
            _event(MockEventKind.TESTS_RUN, 90, status="failed", passed=3, failed=1, errors=0),
            _event(MockEventKind.FILE_SAVED, 125, path="a.py", added=1, removed=1),
            _event(MockEventKind.COMMAND_RUN, 130, command="pytest -q", exitCode=0),
        ],
        START,
    )
    assert lines == [
        "00:00 session started",
        "01:05-01:10 saved a.py (+3 -1, 2 saves)",
        "01:30 ran tests: failed (3 passed, 1 failed, 0 errors)",
        "02:05 saved a.py (+1 -1)",
        "02:10 ran in the terminal: pytest -q (exit 0)",
    ]


def test_work_record_has_timeline_failures_and_diff() -> None:
    session = MockSession(
        title="Live",
        id="s1",
        kind=MockSessionKind.LIVE,
        started_at=START,
        final_diff="--- a/a.py\n+++ b/a.py\n",
        test_report={
            "status": "failed",
            "passed": 1,
            "failed": 1,
            "errors": 0,
            "cases": [
                {"name": "test_ok", "outcome": "passed", "message": ""},
                {"name": "test_fee", "outcome": "failed", "message": "Traceback\nassert 0 == 75"},
            ],
        },
    )
    record = work_record(session, [_event(MockEventKind.SESSION_STARTED, 0)])
    assert "00:00 session started" in record
    assert (
        "Last test run: failed - 1 passed, 1 failed, 0 errors\n- test_fee: assert 0 == 75" in record
    )
    assert record.endswith("--- a/a.py\n+++ b/a.py")


def test_pasted_transcripts_have_no_work_record() -> None:
    assert work_record(MockSession(title="Pasted", id="s2"), []) == ""
