"""Fakes for the project generator's tests: a sandbox whose hidden test runs
"pass" when the files they check contain what the reference adds, and model
replies carrying tool calls with token usage.

The rules stand in for really running Vitest: each fixture test file names
the source file and the text its feature needs (``RULES``); every ``it``
in it passes when that file in the sandbox contains the text. Docker-backed
tests run the same fixtures for real (``tests/test_project_gen_docker.py``).
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from dayline.adapters.sandbox import InMemorySandboxClient
from tests.mock_fakes import FakeResponse, FakeText, FakeToolUse

SERVICE = "api/src/notes/notes.service.ts"
# Hidden test file (as the model names it) -> (file it checks, text it needs).
RULES: dict[str, tuple[str, str]] = {
    "tags.test.ts": (SERVICE, "normalise("),
    "filter.test.ts": (SERVICE, "wanted"),
}
_DESCRIBE = re.compile(r"describe\('([^']+)'")
_IT = re.compile(r"\bit\('([^']+)'")


def _rule(path: str) -> tuple[str, str] | None:
    name = path.split("-", 1)[-1]  # "stage1-tags.test.ts" -> "tags.test.ts"
    return RULES.get(name)


class RuleSandbox(InMemorySandboxClient):
    """Runs hidden tests by :data:`RULES` against the sandbox's own files."""

    def run_hidden_tests(self, sandbox_id: str, files: dict[str, str]) -> dict[str, Any]:
        box_files = self._get(sandbox_id)["files"]
        self.hidden_runs.append(dict(files))
        cases = []
        for path, source in sorted(files.items()):
            rule = _rule(path)
            ok = rule is not None and rule[1] in box_files.get(rule[0], "")
            describe = (_DESCRIBE.findall(source) or ["suite"])[0]
            for title in _IT.findall(source):
                cases.append(
                    {
                        "classname": f".dayline/hidden/{path}",
                        "name": f"{describe} > {title}",
                        "outcome": "passed" if ok else "failed",
                        "message": "" if ok else "expected the feature",
                    }
                )
        failed = sum(c["outcome"] != "passed" for c in cases)
        return {
            "status": "error" if not cases else "failed" if failed else "passed",
            "passed": len(cases) - failed,
            "failed": failed,
            "errors": 0,
            "output": "",
            "cases": cases,
        }


def usage(input_tokens: int = 1000, output_tokens: int = 500) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=200,
        cache_creation_input_tokens=100,
    )


def tool_reply(name: str, payload: dict[str, Any], tool_id: str = "tu_1") -> FakeResponse:
    response = FakeResponse([FakeToolUse(name=name, input=payload, id=tool_id)])
    response.usage = usage()  # type: ignore[attr-defined]
    return response


def text_reply(text: str) -> FakeResponse:
    response = FakeResponse([FakeText(text)])
    response.usage = usage(output_tokens=20)  # type: ignore[attr-defined]
    return response
