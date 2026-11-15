"""The in-session coding assistant's agent loop (``mock/assistant.py``) with
a scripted Anthropic client: which tools each mode gets, that only edit mode
can draft edits (and nothing ever writes), how edits are drafted, and that
the loop is bounded, cancellable, and fed the earlier turns."""

from __future__ import annotations

from typing import Any

import pytest

from dayline.mock.assistant import (
    MAX_TOOL_ROUNDS,
    PastTurn,
    Proposal,
    ToolError,
    TurnError,
    TurnResult,
    Workspace,
    apply_edits,
    clean_path,
    history_messages,
    stream_turn,
    tools_for,
)
from tests.mock_fakes import FakeAnthropic, FakeMessages, FakeResponse, FakeText, FakeToolUse

SERVICE = "def add(a, b):\n    return a - b\n"


class Files:
    """A read-only workspace over a dict, counting every read."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = dict(files)
        self.reads: list[str] = []

    def read(self, path: str) -> dict[str, Any]:
        self.reads.append(path)
        if path not in self.files:
            raise ToolError(f"No file {path!r}")
        return {"content": self.files[path], "version": f"v-{hash(self.files[path])}"}

    def workspace(self, report: dict[str, Any] | None = None) -> Workspace:
        return Workspace(
            list_files=lambda: [{"path": p, "size": len(c)} for p, c in sorted(self.files.items())],
            read_file=self.read,
            snapshot=lambda: dict(self.files),
            test_report=lambda: report,
            commands=lambda: [{"command": "pytest -q", "exitCode": 1, "at": 0}],
        )


def _client(*responses: Any) -> FakeAnthropic:
    return FakeAnthropic(FakeMessages(list(responses)))


def _call(name: str, payload: dict[str, Any], tool_id: str = "tu_1") -> FakeResponse:
    return FakeResponse([FakeToolUse(name=name, input=payload, id=tool_id)])


def _run(
    client: FakeAnthropic,
    mode: str,
    files: Files,
    prompt: str = "help",
    history: list[PastTurn] | None = None,
    **kwargs: Any,
) -> tuple[list[tuple[str, Any]], TurnResult]:
    events = list(
        stream_turn(client, "model-x", mode, history or [], prompt, files.workspace(), **kwargs)  # type: ignore[arg-type]
    )
    kind, result = events[-1]
    assert kind == "result"
    return events, result


def _tool_results(client: FakeAnthropic, call: int) -> list[dict[str, Any]]:
    """The tool_result blocks sent back in the ``call``-th request."""
    content: list[dict[str, Any]] = client.messages.calls[call]["messages"][-1]["content"]
    return content


# --------------------------------------------------------------------------- #
# Modes and permissions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["ask", "plan"])
def test_ask_and_plan_never_get_the_edit_tool(mode: str) -> None:
    names = {t["name"] for t in tools_for(mode, Files({}).workspace())}  # type: ignore[arg-type]
    assert "propose_edit" not in names
    assert {"list_files", "read_file", "search", "get_test_report", "get_terminal_log"} <= names


def test_edit_mode_gets_the_edit_tool_and_server_logs_plug_in_when_present() -> None:
    workspace = Files({}).workspace()
    assert "propose_edit" in {t["name"] for t in tools_for("edit", workspace)}
    assert "get_server_logs" not in {t["name"] for t in tools_for("edit", workspace)}
    with_logs = Workspace(
        list_files=workspace.list_files,
        read_file=workspace.read_file,
        snapshot=workspace.snapshot,
        test_report=workspace.test_report,
        commands=workspace.commands,
        server_logs=lambda: "GET / 200",
    )
    assert "get_server_logs" in {t["name"] for t in tools_for("ask", with_logs)}


@pytest.mark.parametrize("mode", ["ask", "plan"])
def test_ask_and_plan_refuse_an_edit_call_and_draft_nothing(mode: str) -> None:
    files = Files({"calc.py": SERVICE})
    edit = {"path": "calc.py", "summary": "fix", "new_content": "x = 1\n"}
    client = _client(_call("propose_edit", edit), FakeResponse([FakeText("Change - to +.")]))

    events, result = _run(client, mode, files)

    assert result.proposals == []
    assert not [e for e in events if e[0] == "proposal"]
    (tool_result,) = _tool_results(client, 1)
    assert tool_result["is_error"] is True
    assert "cannot edit" in tool_result["content"]
    assert files.files == {"calc.py": SERVICE}
    # The tools offered to the model never included it either.
    assert "propose_edit" not in {t["name"] for t in client.messages.calls[0]["tools"]}


def test_the_mode_shapes_the_system_prompt() -> None:
    for mode, marker in (("ask", "Mode: ASK"), ("plan", "numbered list"), ("edit", "NOT applied")):
        client = _client(FakeResponse([FakeText("ok")]))
        _run(client, mode, Files({}))
        assert marker in client.messages.calls[0]["system"]
        assert client.messages.calls[0]["messages"][-1]["content"] == f"[{mode} mode] help"


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #


def test_read_tools_return_numbered_lines_matches_tests_and_commands() -> None:
    files = Files({"calc.py": SERVICE, "README.md": "Fix add.\n"})
    client = _client(
        FakeResponse(
            [
                FakeToolUse("read_file", {"path": "./calc.py"}, id="a"),
                FakeToolUse("search", {"pattern": "RETURN"}, id="b"),
                FakeToolUse("get_test_report", {}, id="c"),
                FakeToolUse("get_terminal_log", {}, id="d"),
                FakeToolUse("list_files", {}, id="e"),
            ]
        ),
        FakeResponse([FakeText("It subtracts.")]),
    )

    events, result = _run(client, "ask", files)

    read, search, tests, terminal, listing = (r["content"] for r in _tool_results(client, 1))
    assert read == "   1| def add(a, b):\n   2|     return a - b"
    assert search == "calc.py:2: return a - b"
    assert "not been run" in tests
    assert terminal == "$ pytest -q  (exit 1)"
    assert listing == "README.md (9 bytes)\ncalc.py (32 bytes)"
    assert result.text == "It subtracts."
    assert result.tools == [
        "read calc.py",
        'searched "RETURN" (1 matches)',
        "checked tests",
        "checked the terminal",
        "listed files (2)",
    ]
    assert [e[1] for e in events if e[0] == "tool"] == result.tools
    assert ("status", "Reading code…") in events


def test_a_bad_tool_call_goes_back_to_the_model_as_an_error() -> None:
    client = _client(
        FakeResponse(
            [
                FakeToolUse("read_file", {"path": "nope.py"}, id="a"),
                FakeToolUse("read_file", {"path": "../etc/passwd"}, id="b"),
                FakeToolUse("search", {"pattern": "("}, id="c"),
            ]
        ),
        FakeResponse([FakeText("Sorry.")]),
    )
    _, result = _run(client, "ask", Files({}))
    errors = _tool_results(client, 1)
    assert all(r["is_error"] for r in errors)
    assert "not a path inside" in errors[1]["content"]
    assert "Bad regular expression" in errors[2]["content"]
    assert result.status == "done"


def test_clean_path_keeps_the_assistant_inside_the_repo() -> None:
    assert clean_path("./src/a.py") == "src/a.py"
    assert clean_path("src//b/../a.py") == "src/a.py"
    for bad in ("", "/etc/passwd", "..", "../x", ".dayline/hidden/t.py", ".git/config"):
        with pytest.raises(ToolError):
            clean_path(bad)


# --------------------------------------------------------------------------- #
# Drafting edits
# --------------------------------------------------------------------------- #


def test_edit_mode_drafts_the_exact_new_content_without_writing() -> None:
    files = Files({"calc.py": SERVICE})
    edit = {
        "path": "calc.py",
        "summary": "Add instead of subtract.",
        "edits": [{"old_text": "return a - b", "new_text": "return a + b"}],
    }
    client = _client(_call("propose_edit", edit), FakeResponse([FakeText("Fixed `add`.")]))

    events, result = _run(client, "edit", files)

    (proposal,) = result.proposals
    assert proposal.path == "calc.py"
    assert proposal.content == "def add(a, b):\n    return a + b\n"
    assert proposal.before == SERVICE
    assert proposal.base_version == files.read("calc.py")["version"]
    assert proposal.counts() == (1, 1)
    assert "-    return a - b" in proposal.diff() and "+    return a + b" in proposal.diff()
    assert [e[1] for e in events if e[0] == "proposal"] == [proposal]
    assert files.files == {"calc.py": SERVICE}
    assert "not applied" in _tool_results(client, 1)[0]["content"]


def test_a_second_edit_to_the_same_file_builds_on_the_first() -> None:
    files = Files({"calc.py": SERVICE})
    first = {"path": "calc.py", "summary": "Fix", "edits": [{"old_text": "-", "new_text": "+"}]}
    second = {
        "path": "calc.py",
        "summary": "Rename",
        "edits": [{"old_text": "def add", "new_text": "def plus"}],
    }
    client = _client(
        _call("propose_edit", first, "a"),
        _call("propose_edit", second, "b"),
        FakeResponse([FakeText("Done.")]),
    )

    events, result = _run(client, "edit", files)

    (proposal,) = result.proposals
    assert proposal.content == "def plus(a, b):\n    return a + b\n"
    assert proposal.before == SERVICE
    drafts = [e[1] for e in events if e[0] == "proposal"]
    assert len(drafts) == 2 and drafts[0].id == drafts[1].id == proposal.id


def _swap(old: str, new: str) -> list[dict[str, str]]:
    return [{"old_text": old, "new_text": new}]


def test_new_files_and_invalid_edits() -> None:
    files = Files({"calc.py": SERVICE})
    calls: list[dict[str, Any]] = [
        {"path": "test_calc.py", "new_content": "assert 1\n"},
        {"path": "calc.py", "edits": _swap("zzz", "")},
        {"path": "calc.py", "edits": _swap("a", "c")},
        {"path": "missing.py", "edits": _swap("a", "b")},
        {"path": "calc.py"},
        {"path": "calc.py", "new_content": SERVICE},
    ]
    blocks = [
        FakeToolUse("propose_edit", {"summary": "x", **call}, id=f"t{i}")
        for i, call in enumerate(calls)
    ]
    client = _client(FakeResponse(list(blocks)), FakeResponse([FakeText("Partly done.")]))

    _, result = _run(client, "edit", files)

    (proposal,) = result.proposals
    assert proposal.new_file and proposal.base_version == "" and proposal.before is None
    assert proposal.diff().startswith("--- /dev/null\n+++ b/test_calc.py")
    messages = [r["content"] for r in _tool_results(client, 1)[1:]]
    assert "not found" in messages[0]
    assert "appears" in messages[1]
    assert "does not exist" in messages[2]
    assert "exactly one" in messages[3]
    assert "changes nothing" in messages[4]


def test_apply_edits_runs_in_order() -> None:
    edits = [{"old_text": "a", "new_text": "b"}, {"old_text": "bc", "new_text": "X"}]
    assert apply_edits("ac", edits) == "X"


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


def test_text_streams_as_deltas_across_rounds() -> None:
    client = _client(
        FakeResponse([FakeText("Let me look."), FakeToolUse("list_files", {})]),
        FakeResponse([FakeText("Two files.")]),
    )
    events, result = _run(client, "ask", Files({"a": "", "b": ""}))
    deltas = "".join(e[1] for e in events if e[0] == "delta")
    assert deltas == result.text == "Let me look.\n\nTwo files."


def test_the_tool_loop_is_bounded() -> None:
    client = _client(*[_call("list_files", {}, f"t{i}") for i in range(MAX_TOOL_ROUNDS)])
    _, result = _run(client, "ask", Files({}))
    assert len(client.messages.calls) == MAX_TOOL_ROUNDS
    assert result.status == "done"
    assert f"Stopped after {MAX_TOOL_ROUNDS}" in result.text


def test_cancelling_stops_mid_stream_and_keeps_what_was_written() -> None:
    flag = {"stop": False}
    messages = FakeMessages([FakeResponse([FakeText("one two three four")])])

    def stop_after_two_words(event: Any) -> None:
        if event.type == "content_block_delta" and event.delta.text == "two ":
            flag["stop"] = True

    messages.before_event = stop_after_two_words
    client = FakeAnthropic(messages)

    _, result = _run(client, "ask", Files({}), cancelled=lambda: flag["stop"])

    assert result.status == "cancelled"
    assert result.text == "one"
    assert messages.streams[0].closed


def test_a_reply_cut_off_mid_edit_is_an_error_but_cut_text_is_kept() -> None:
    cut = FakeResponse([FakeToolUse("propose_edit", {"path": "a"})], stop_reason="max_tokens")
    with pytest.raises(TurnError):
        _run(_client(cut), "edit", Files({}))
    long = FakeResponse([FakeText("A very long")], stop_reason="max_tokens")
    _, result = _run(_client(long), "ask", Files({}))
    assert result.text.startswith("A very long") and "length limit" in result.text


def test_earlier_turns_go_back_as_text_with_what_happened_to_each_edit() -> None:
    history = [
        PastTurn(mode="plan", prompt="How?", reply="1. Fix add."),
        PastTurn(
            mode="edit",
            prompt="Do it",
            reply="Proposed.",
            edits=[("calc.py", "Fix", "rejected"), ("t.py", "Test", "accepted")],
        ),
    ]
    client = _client(FakeResponse([FakeText("ok")]))
    _run(client, "ask", Files({}), prompt="Why?", history=history)
    sent = client.messages.calls[0]["messages"]
    assert sent[0] == {"role": "user", "content": "[plan mode] How?"}
    assert sent[1] == {"role": "assistant", "content": "1. Fix add."}
    assert "calc.py: rejected; t.py: accepted" in sent[3]["content"]
    assert sent[4] == {"role": "user", "content": "[ask mode] Why?"}
    assert history_messages([PastTurn(mode="ask", prompt="x", reply="")])[1]["content"] == (
        "(no reply)"
    )


def test_proposal_diff_is_bounded() -> None:
    big = "x\n" * 100_000
    proposal = Proposal(id="p", path="a", summary="", base_version="", before=None, content=big)
    assert len(proposal.diff()) < 61_000
