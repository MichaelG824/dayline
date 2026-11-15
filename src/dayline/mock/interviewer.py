"""The interviewer in a staged round.

It speaks at each stage transition (wrapping up the last stage and opening
the next one), when the candidate asks for a follow-up, and when the
candidate says something. Every turn it reads the candidate's current code,
the last hidden test run, the stage's interviewer notes, and the chat so
far, so its questions can point at the candidate's actual code ("your `get`
moves the node to the front...").

The reply is plain text (no tools): the chat is free-form, and nothing the
interviewer says changes the round's state - only test runs and skips do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

import anthropic

from dayline.mock.staged import Stage, StagedProblem
from dayline.models import StageAttempt, StageStatus

Trigger = Literal["stage_start", "follow_up", "message"]

MAX_CODE_CHARS = 40_000
MAX_FAILURES_SHOWN = 8
MAX_CHAT_MESSAGES = 60
MAX_REPLY_TOKENS = 1024


class InterviewerError(Exception):
    """The model replied with nothing usable."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["interviewer", "candidate"]
    text: str
    stage: int  # 1-based; the stage that was active when it was said.


SYSTEM_PROMPT = """You are the interviewer in a staged practical programming \
round. The candidate writes real code in a sandbox; each stage adds a \
production requirement to the code they already wrote, the way a senior \
engineer adds follow-ups in a real interview. Hidden tests decide when a \
stage passes; your job is the conversation.

How to behave:
- Ground every question in the candidate's actual code: name their \
functions, fields, and lines ("your `get` unlinks the node and pushes it to \
the front - what does that mean for..."). Never ask a generic textbook \
question you could have asked without reading their code.
- One question at a time. Keep replies short: 2-5 sentences, like speech.
- Never write the solution or paste corrected code. A hint, when asked for \
or when they are clearly stuck, is a nudge toward where to look, not the fix.
- Do not reveal the hidden tests (names, inputs, or how many there are) or \
what later stages will ask. You may describe a failing behaviour in plain \
words if they ask why a run failed.
- Answer clarifying questions about the current stage's requirements \
directly, from the stage prompt. If the prompt leaves a choice to the \
candidate, say so and ask what they would choose and why.
- Use your interviewer notes to decide what to probe; they are private.
- Plain text only. Use `backticks` for code identifiers; no headings, no \
bullet lists, no code blocks."""

_TRIGGER_INSTRUCTIONS: dict[Trigger, str] = {
    "stage_start": "The candidate just reached this stage. {wrap_up}Introduce the \
stage's new requirement in a sentence or two of your own words (they can read \
the full prompt), then ask one question about how their current code will \
need to change for it - point at the specific part of their code.",
    "follow_up": "The candidate asked for your next question. Ask the most useful \
follow-up from your notes for this stage that has not been covered yet, \
grounded in their current code and test results.",
    "message": "Reply to the candidate's last message. If they explained a \
choice, probe it; if they asked something, answer it within the rules.",
}

_WRAP_UP = "In one sentence, acknowledge how the previous stage ended ({how}), \
referring to something specific in their code. "

_CLOSING = "Every stage is done. Close the round: in 2-4 sentences, name one \
thing their code did well and the one thing you would push them on, grounded \
in their code. Do not ask a question."


def _stage_header(stage: Stage, attempt: StageAttempt) -> str:
    return f"Stage {stage.number}: {stage.title} ({attempt.status.value})"


def _code_section(code: dict[str, str]) -> str:
    if not code:
        return "(the candidate's files could not be read)"
    parts, budget = [], MAX_CODE_CHARS
    for path, content in sorted(code.items()):
        text = content if len(content) <= budget else content[:budget] + "\n… (cut)"
        budget -= len(text)
        parts.append(f"--- {path} ---\n{text}")
        if budget <= 0:
            break
    return "\n".join(parts)


def _tests_section(report: dict[str, Any] | None) -> str:
    if not report:
        return "The candidate has not run the hidden tests for this stage yet."
    head = (
        f"Last hidden test run: {report.get('status')} - {report.get('passed', 0)} passed, "
        f"{report.get('failed', 0)} failed, {report.get('errors', 0)} errors."
    )
    cases = report.get("cases")
    failing = [
        c
        for c in (cases if isinstance(cases, list) else [])
        if isinstance(c, dict) and c.get("outcome") in ("failed", "error")
    ]
    lines = [head]
    for case in failing[:MAX_FAILURES_SHOWN]:
        message = str(case.get("message") or "").strip().splitlines()
        lines.append(f"- {case.get('name')}: {message[-1] if message else case.get('outcome')}")
    if report.get("status") in ("error", "timeout") and not failing:
        lines.append(str(report.get("output") or "")[-1500:])
    return "\n".join(lines)


def _chat_section(chat: list[ChatMessage]) -> str:
    if not chat:
        return "(nothing said yet)"
    shown = chat[-MAX_CHAT_MESSAGES:]
    lines = [] if len(shown) == len(chat) else ["… (earlier messages cut)"]
    lines += [
        f"[stage {m.stage}] {'Interviewer' if m.role == 'interviewer' else 'Candidate'}: {m.text}"
        for m in shown
    ]
    return "\n".join(lines)


def build_prompt(
    problem: StagedProblem,
    stages: list[StageAttempt],
    index: int | None,
    code: dict[str, str],
    chat: list[ChatMessage],
    trigger: Trigger,
) -> str:
    """The user turn for one interviewer reply. ``index`` is the active
    stage's 0-based index, or ``None`` once every stage is done."""
    progress = "\n".join(
        _stage_header(stage, attempt)
        for stage, attempt in zip(problem.stages, stages, strict=True)
        if attempt.status is not StageStatus.LOCKED
    )
    if index is None:
        stage_part = "Every stage is done."
        report = next((a.report for a in reversed(stages) if a.report), None)
        instruction = _CLOSING
    else:
        stage, attempt = problem.stages[index], stages[index]
        stage_part = (
            f"Current stage prompt (the candidate sees this):\n{stage.prompt_md.strip()}\n\n"
            f"Your private notes for this stage:\n{stage.notes_md.strip()}"
        )
        report = attempt.report
        instruction = _TRIGGER_INSTRUCTIONS[trigger]
        if trigger == "stage_start":
            previous = stages[index - 1] if index > 0 else None
            if previous is None:
                wrap_up = "This is the first stage, so open the round with a one-line greeting. "
            else:
                how = (
                    "its hidden tests passed"
                    if previous.status is StageStatus.PASSED
                    else "the candidate skipped it without passing"
                )
                wrap_up = _WRAP_UP.format(how=how)
            instruction = instruction.format(wrap_up=wrap_up)

    return "\n\n".join(
        [
            f"# Problem: {problem.title}",
            f"## Stages so far\n{progress}",
            f"## {stage_part}",
            f"## The candidate's code now\n{_code_section(code)}",
            f"## Tests\n{_tests_section(report)}",
            f"## Conversation so far\n{_chat_section(chat)}",
            f"## Your turn\n{instruction}",
        ]
    )


def interviewer_reply(
    client: anthropic.Anthropic,
    model: str,
    problem: StagedProblem,
    stages: list[StageAttempt],
    index: int | None,
    code: dict[str, str],
    chat: list[ChatMessage],
    trigger: Trigger,
) -> str:
    """The interviewer's next message."""
    prompt = build_prompt(problem, stages, index, code, chat, trigger)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_REPLY_TOKENS,
        system=SYSTEM_PROMPT,
        messages=cast(Any, [{"role": "user", "content": prompt}]),
    )
    text = "".join(getattr(b, "text", "") for b in response.content if b.type == "text").strip()
    if not text:
        raise InterviewerError("The interviewer had nothing to say. Try again.")
    return text
