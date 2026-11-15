"""Run a staged problem's hidden tests the way the sandbox runner does, but in
a local subprocess: the hidden files in an isolated folder of the workspace,
the workspace importable, the candidate's own pytest config ignored (see
``hidden_test_cmd`` in sandbox/packs/python/pack.toml). Returns the runner's
report JSON, built by the runner's own JUnit parser."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from dayline_runner.junit import build_report, parse_junit

HIDDEN_DIR = ".dayline/hidden"


def run_hidden(workspace: dict[str, str], hidden: dict[str, str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        files = {**workspace, **{f"{HIDDEN_DIR}/{path}": text for path, text in hidden.items()}}
        for path, content in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        junit = root / "junit.xml"
        cmd = [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--rootdir={HIDDEN_DIR}", "-c", "/dev/null", f"--junitxml={junit}", HIDDEN_DIR,
        ]  # fmt: skip
        started = time.monotonic()
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
        cases = parse_junit(junit.read_bytes()) if junit.exists() else None
        report = build_report(
            cases,
            exit_code=result.returncode,
            output=result.stdout + result.stderr,
            duration_s=time.monotonic() - started,
            timed_out=False,
        )
        return report.to_json()
