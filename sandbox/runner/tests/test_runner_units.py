"""Runner logic that needs no Docker: packs, JUnit parsing, workspace paths."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from dayline_runner.commands import parse_command_log
from dayline_runner.junit import build_report, parse_junit, tail
from dayline_runner.packs import JUNIT_PATH, PackError, load_pack, load_packs
from dayline_runner.workspace import (
    WorkspacePathError,
    clean_path,
    content_version,
    file_tar,
    parse_listing,
    read_snapshot,
)

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


def test_shipped_packs_load_with_content_hashed_images() -> None:
    packs = load_packs(PACKS_DIR)
    assert set(packs) >= {"python", "typescript"}
    for pack in packs.values():
        assert JUNIT_PATH in pack.test_cmd and "{junit}" not in pack.test_cmd
        assert pack.image.startswith(f"dayline-pack-{pack.name}:")


def _pack(tmp_path: Path, toml: str, name: str = "demo") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "Dockerfile").write_text("FROM scratch\n")
    (folder / "pack.toml").write_text(toml)
    return folder


def test_image_tag_changes_when_the_pack_changes(tmp_path: Path) -> None:
    folder = _pack(tmp_path, 'name = "demo"\ntest_cmd = "t --out {junit}"\n')
    before = load_pack(folder).image
    (folder / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    assert load_pack(folder).image != before


@pytest.mark.parametrize(
    "toml",
    [
        'name = "other"\ntest_cmd = "t {junit}"\n',  # Name differs from the folder.
        'name = "demo"\ntest_cmd = "pytest"\n',  # No JUnit output.
        'name = "demo"\ntest_cmd = "t {junit}"\ntest_timeout_s = 0\n',
        "name = ",  # Not TOML.
    ],
)
def test_invalid_packs_are_rejected(tmp_path: Path, toml: str) -> None:
    with pytest.raises(PackError):
        load_pack(_pack(tmp_path, toml))


PYTEST_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.test_calc" name="test_add" time="0.001"/>
  <testcase classname="tests.test_calc" name="test_sub" time="0.002">
    <failure message="assert 0 == 4">def test_sub():
&gt;       assert add(2, 2) == 4
E       assert 0 == 4</failure>
  </testcase>
  <testcase classname="tests.test_calc" name="test_io"><error message="fixture missing"/></testcase>
  <testcase classname="tests.test_calc" name="test_later"><skipped message="todo"/></testcase>
</testsuite></testsuites>"""


def test_junit_cases_and_report_put_failures_first() -> None:
    cases = parse_junit(PYTEST_XML)
    report = build_report(cases, exit_code=1, output="1 failed", duration_s=0.5, timed_out=False)
    assert (report.status, report.passed, report.failed, report.errors, report.skipped) == (
        "failed",
        1,
        1,
        1,
        1,
    )
    assert [c.name for c in report.cases][-1] == "test_add"
    failure = next(c for c in report.cases if c.name == "test_sub")
    # The traceback body wins over the one-line message it already contains.
    assert "assert add(2, 2) == 4" in failure.message


def test_report_statuses() -> None:
    passed = parse_junit(b'<testsuite><testcase name="ok"/></testsuite>')
    assert build_report(passed, exit_code=0, output="", duration_s=1, timed_out=False).status == (
        "passed"
    )
    # No XML (e.g. a syntax error before collection) or no tests: could not run.
    assert build_report(None, exit_code=2, output="", duration_s=1, timed_out=False).status == (
        "error"
    )
    assert build_report([], exit_code=5, output="", duration_s=1, timed_out=False).status == "error"
    assert build_report(passed, exit_code=124, output="", duration_s=60, timed_out=True).status == (
        "timeout"
    )


def test_bad_junit_and_long_output() -> None:
    with pytest.raises(ValueError, match="Unreadable"):
        parse_junit(b"<testsuite><testcase")
    cut = tail("x" * 30_000)
    assert cut.startswith("…(earlier output cut)") and len(cut) < 21_000


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../x", "a/../../x", "a\\b", "node_modules/x"])
def test_unsafe_paths_are_rejected(path: str) -> None:
    with pytest.raises(WorkspacePathError):
        clean_path(path)


def test_paths_are_normalised() -> None:
    assert clean_path("src/./app.py") == "src/app.py"
    assert clean_path("-rf") == "-rf"  # Callers always prefix "./".


def test_listing_joins_sizes_and_hashes_and_skips_bad_names() -> None:
    sha = content_version(b"print(1)\n")
    stats = b"9 1.5 app.py\x0012 2.5 big.bin\x007 3.0 ../escape\x00"
    hashes = f"{sha}  ./app.py\x00".encode()
    entries = parse_listing(stats, hashes)
    assert [(e.path, e.version) for e in entries] == [("app.py", sha), ("big.bin", "2.5-12")]


def test_tar_round_trip_keeps_text_and_skips_binary_and_ignored() -> None:
    tar_bytes = file_tar({"src/app.py": b"x = 1\n", "logo.png": b"\x89PNG\xff"})
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        members = tar.getmembers()
    assert {m.name for m in members} == {"src", "src/app.py", "logo.png"}
    assert all(m.uid == 1000 for m in members)

    # get_archive wraps everything in a "workspace/" folder.
    wrapped = io.BytesIO()
    with tarfile.open(fileobj=wrapped, mode="w") as tar:
        for name, data in [
            ("workspace/src/app.py", b"x = 1\n"),
            ("workspace/logo.png", b"\x89PNG\xff"),
            ("workspace/__pycache__/app.pyc", b"x"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    files, skipped = read_snapshot([wrapped.getvalue()])
    assert files == {"src/app.py": "x = 1\n"}
    assert skipped == ["logo.png"]


def test_command_log_skips_malformed_lines() -> None:
    log = (
        "1700000000\t0\tpytest -q\n"
        "not a line\n"
        "1700000005\tx\tls\n"  # Exit code is not a number.
        "1700000009\t1\t  \n"  # Blank command.
        "1700000010\t2\tnpm test\n"
    )
    runs = parse_command_log(log)
    assert [(r.at, r.exit_code, r.command) for r in runs] == [
        (1700000000.0, 0, "pytest -q"),
        (1700000010.0, 2, "npm test"),
    ]
