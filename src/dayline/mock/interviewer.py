"""The interviewer in a staged round.

It speaks at each stage transition (wrapping up the last stage and opening
the next one, or delivering a generated round's change request when its
minute comes), when the candidate asks for a follow-up, when the candidate
says something, and - realistic style only - when a check-in finds them
clearly stuck. Every turn it reads the candidate's current code, the last
hidden test run, the stage's interviewer notes, and the chat so far, so its
questions can point at the candidate's actual code ("your `get` moves the
node to the front...").

Two styles (``InterviewerStyle``):

- ``coach``: probes each stage and asks follow-ups on request (the original
  behaviour, the default for built-in rounds).
- ``realistic`` (the default for generated rounds): behaves like a real
  interviewer - quiet while the candidate codes, no praise, never confirms
  correctness, answers requirement questions, rare pointed pushback, and
  feedback only at the end. Code, not the prompt alone, enforces the parts
  that can be checked: whether a check-in speaks at all and whether a hint
  is allowed (:func:`stuck_reason` over :class:`Signals` read from the
  session's events), and a reply that praises, confirms correctness, pastes
  code, or runs long is sent back once to be rewritten
  (:func:`speaking_problems`).

The reply is plain text (no tools): the chat is free-form, and nothing the
interviewer says changes the round's state - only test runs and skips do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

import anthropic

from dayline.mock.staged import Stage, StagedProblem
from dayline.models import InterviewerStyle, MockEvent, MockEventKind, StageAttempt, StageStatus

Trigger = Literal["stage_start", "follow_up", "message", "check_in"]

MAX_CODE_CHARS = 40_000
MAX_FAILURES_SHOWN = 8
MAX_CHAT_MESSAGES = 60
MAX_REPLY_TOKENS = 1024

# Realistic style: when the candidate counts as clearly stuck.
STUCK_FAILING_RUNS = 3  # Test runs in a row that did not pass.
STUCK_IDLE_S = 8 * 60  # Nothing saved, run, asked, or said for this long.
# A check-in never follows the interviewer's last message sooner than this.
CHECK_IN_COOLDOWN_S = 5 * 60
# Realistic replies are spoken asides, not lectures (the closing is longer).
MAX_REALISTIC_SENTENCES = 4
MAX_CLOSING_SENTENCES = 7


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

REALISTIC_SYSTEM_PROMPT = """You are the interviewer in a timed, AI-assisted \
practical coding round. The candidate works on a real project in a sandbox, \
with an AI coding assistant they may use as they like; hidden tests decide \
whether each stage passes. Behave exactly like a real, experienced \
interviewer at a good company, not like a tutor.

How to behave:
- Stay quiet while they code. Speak only when spoken to, when the round \
calls for it (opening, a change request, the close), or when told they are \
clearly stuck. Short, plain, spoken sentences: 1-3 of them.
- No praise and no reassurance while the round runs: never "great", \
"nice", "good question", "looks good", "you're on the right track".
- Never confirm or deny that their code or approach is correct. If they \
ask "is this right?", turn it back: ask how they would check it (a test, \
the running app, a case to try).
- Never write code for them or dictate the fix, even when asked ("write it \
for me"): say that is their call and the assistant is there if they want it.
- Answer clarifying questions about the requirements directly and \
concretely, from the stage prompt and your notes, like a product owner \
would. If the prompt leaves a choice open, say it is their call.
- Give a hint only when the turn says they are clearly stuck, and then only \
a nudge about where to look, never the answer.
- Rarely, when their code has a real risk, push back with one pointed \
question that names their code ("what happens to `tags` when the note is \
saved twice?"). Never ask generic textbook questions.
- Do not reveal the hidden tests (names, inputs, or how many) or what comes \
later in the round. Save all feedback for the end of the round.
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
    "check_in": "The candidate seems stuck ({reason}). Check in briefly: ask \
where they are, and if they are clearly going nowhere, a nudge toward where \
to look - not the fix.",
}

_REALISTIC_INSTRUCTIONS: dict[Trigger, str] = {
    "stage_start": "Open the round in one or two sentences: a brief hello, \
that the task is in front of them and they can ask you about requirements \
any time. Then stop - do not ask about their approach.",
    "follow_up": "The candidate asked if you have anything for them. Usually \
you do not: say so in a few words and let them keep going. Only if their \
current code has a real risk, ask one short pointed question about it, \
naming the code.",
    "message": "Reply to the candidate's last message within the rules. {hint}",
    "check_in": "They seem stuck ({reason}). Check in the way a real \
interviewer would: one short sentence asking where they are, or, if they \
are clearly going in circles, one nudge about where to look - never the fix.",
}

_HINT_ALLOWED = "They are clearly stuck ({reason}), so if they want help you \
may give one small nudge about where to look - not the fix."
_HINT_REFUSED = "Nothing shows they are stuck, so give no hint: if they ask \
for one, ask what they have tried or what they would check first."

_CHANGE_REQUEST = 'Time for the change request (the stage prompt above). \
Interrupt the candidate with it in your own words, briefly, the way a real \
interviewer does: "OK, the PM just came back - ...". In 2-4 sentences say \
what changed and why it matters to the product. Do not suggest how to build \
it, do not mention tests, and {previous}'

_REALISTIC_NEXT_STAGE = "The candidate just reached a new stage. Introduce \
its requirement in one or two sentences of your own words (they can read \
the full prompt). Say nothing about how the previous stage went."

_WRAP_UP = "In one sentence, acknowledge how the previous stage ended ({how}), \
referring to something specific in their code. "

_CLOSING = "Every stage is done. Close the round: in 2-4 sentences, name one \
thing their code did well and the one thing you would push them on, grounded \
in their code. Do not ask a question."

_REALISTIC_CLOSING = "The round is over; now, and only now, give your \
feedback. In 3-6 plain sentences: the most important thing to improve, then \
one thing that worked, both grounded in their code and how they worked \
(including how they used the assistant). Be direct. Do not ask a question."


# --------------------------------------------------------------------------- #
# Speaking rules (realistic style), decided in code
# --------------------------------------------------------------------------- #

_HELP = re.compile(
    r"\b(stuck|hint|no idea|lost|help me|don'?t know (how|where|what)|"
    r"not sure (how|where|what))\b",
    re.IGNORECASE,
)
# What counts as the candidate doing something (not the interviewer talking).
_ACTIVITY = frozenset(
    {
        MockEventKind.SESSION_STARTED,
        MockEventKind.FILE_SAVED,
        MockEventKind.TESTS_RUN,
        MockEventKind.STAGE_TESTS_RUN,
        MockEventKind.CANDIDATE_MESSAGE,
        MockEventKind.ASSISTANT_PROMPT,
        MockEventKind.ASSISTANT_EDIT_DECIDED,
        MockEventKind.SERVER_ACTION,
        MockEventKind.PREVIEW_RELOADED,
        MockEventKind.STAGE_UNLOCKED,
    }
)
_RUNS = frozenset({MockEventKind.TESTS_RUN, MockEventKind.STAGE_TESTS_RUN})


@dataclass(frozen=True, slots=True)
class Signals:
    """What the session's events say about whether the candidate is stuck."""

    # Test runs (visible or hidden) in a row, most recent last, that did not pass.
    failing_runs: int = 0
    # Seconds since the candidate last did anything; ``None`` if unknown.
    idle_s: float | None = None
    # Their last message says they are stuck or asks for a hint.
    asked_for_help: bool = False
    # Seconds since the interviewer last spoke; ``None`` if it never has.
    since_interviewer_s: float | None = None


def read_signals(events: list[MockEvent], now: datetime) -> Signals:
    failing = 0
    for e in reversed([e for e in events if e.kind in _RUNS]):
        if e.data.get("status") == "passed":
            break
        failing += 1
    last_activity = max((e.at for e in events if e.kind in _ACTIVITY and e.at), default=None)
    last_said = max(
        (e.at for e in events if e.kind is MockEventKind.INTERVIEWER_MESSAGE and e.at),
        default=None,
    )
    chat = [
        e
        for e in events
        if e.kind in (MockEventKind.CANDIDATE_MESSAGE, MockEventKind.INTERVIEWER_MESSAGE)
    ]
    asked = bool(
        chat
        and chat[-1].kind is MockEventKind.CANDIDATE_MESSAGE
        and _HELP.search(str(chat[-1].data.get("text", "")))
    )
    return Signals(
        failing_runs=failing,
        idle_s=(now - last_activity).total_seconds() if last_activity else None,
        asked_for_help=asked,
        since_interviewer_s=(now - last_said).total_seconds() if last_said else None,
    )


def stuck_reason(signals: Signals) -> str | None:
    """Why the candidate counts as clearly stuck, or ``None`` if they do not."""
    if signals.asked_for_help:
        return "they said they are stuck"
    if signals.failing_runs >= STUCK_FAILING_RUNS:
        return f"{signals.failing_runs} test runs in a row have not passed"
    if signals.idle_s is not None and signals.idle_s >= STUCK_IDLE_S:
        return f"nothing saved, run, or asked for {int(signals.idle_s // 60)} minutes"
    return None


def should_check_in(signals: Signals) -> bool:
    """A check-in speaks only when the candidate is clearly stuck, and never
    right after the interviewer last spoke."""
    if stuck_reason(signals) is None:
        return False
    return signals.since_interviewer_s is None or signals.since_interviewer_s >= (
        CHECK_IN_COOLDOWN_S
    )


_PRAISE = re.compile(
    r"\b(great|nice|awesome|excellent|perfect|impressive|well done|good job|"
    r"good (work|call|question|point|thinking|catch|instinct|start|progress)|"
    r"looks good|on the right track)\b",
    re.IGNORECASE,
)
# "Whether it's right" / "if it's correct" is the interviewer declining to say.
_CONFIRMS = re.compile(
    r"(?<!whether )(?<!if )"
    r"\b(that'?s|this is|it'?s|you'?re|that looks|it looks|your (code|solution|fix) is)"
    r" (right|correct|exactly right|working|bug-free)\b|\b(correct|right)!",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[.!?](?:\s|$)")


def speaking_problems(text: str, style: InterviewerStyle, closing: bool = False) -> list[str]:
    """Where a reply breaks the style's rules, as instructions to fix it.
    The coach is left as it always was; the closing may praise."""
    if style is not InterviewerStyle.REALISTIC:
        return []
    problems = []
    if "```" in text:
        problems.append("Do not paste code; describe in words, or turn it back to them.")
    if not closing:
        if _PRAISE.search(text):
            problems.append("No praise or reassurance while the round is running.")
        if _CONFIRMS.search(text):
            problems.append(
                "Never confirm their code or approach is correct; ask how they would check it."
            )
    limit = MAX_CLOSING_SENTENCES if closing else MAX_REALISTIC_SENTENCES
    if len(_SENTENCE.findall(text.strip() + " ")) > limit:
        problems.append(f"Too long: at most {limit} short sentences, like speech.")
    return problems


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


def _previous_note(previous: StageAttempt | None, realistic: bool) -> str:
    """What a change request may say about the stage before it."""
    if previous is not None and previous.status is StageStatus.ACTIVE:
        return "do not mention their earlier work - it is not finished, and that is theirs to \
manage."
    if realistic:
        return "say nothing about how the earlier work went."
    return "then ask one question about which part of their current code it touches first."


def _instruction(
    problem: StagedProblem,
    stages: list[StageAttempt],
    index: int,
    trigger: Trigger,
    style: InterviewerStyle,
    signals: Signals,
) -> str:
    realistic = style is InterviewerStyle.REALISTIC
    stage = problem.stages[index]
    reason = stuck_reason(signals) or "no sign of progress"
    if trigger == "stage_start":
        previous = stages[index - 1] if index > 0 else None
        if stage.timed:
            return _CHANGE_REQUEST.format(previous=_previous_note(previous, realistic))
        if realistic:
            return (
                _REALISTIC_INSTRUCTIONS["stage_start"]
                if previous is None
                else (_REALISTIC_NEXT_STAGE)
            )
        if previous is None:
            wrap_up = "This is the first stage, so open the round with a one-line greeting. "
        else:
            how = (
                "its hidden tests passed"
                if previous.status is StageStatus.PASSED
                else "the candidate skipped it without passing"
            )
            wrap_up = _WRAP_UP.format(how=how)
        return _TRIGGER_INSTRUCTIONS["stage_start"].format(wrap_up=wrap_up)
    if not realistic:
        return _TRIGGER_INSTRUCTIONS[trigger].format(reason=reason)
    hint = (
        _HINT_ALLOWED.format(reason=reason) if stuck_reason(signals) is not None else _HINT_REFUSED
    )
    return _REALISTIC_INSTRUCTIONS[trigger].format(reason=reason, hint=hint)


def build_prompt(
    problem: StagedProblem,
    stages: list[StageAttempt],
    index: int | None,
    code: dict[str, str],
    chat: list[ChatMessage],
    trigger: Trigger,
    style: InterviewerStyle = InterviewerStyle.COACH,
    signals: Signals | None = None,
) -> str:
    """The user turn for one interviewer reply. ``index`` is the stage the
    candidate is in (0-based), or ``None`` once every stage is done."""
    progress = "\n".join(
        _stage_header(stage, attempt)
        for stage, attempt in zip(problem.stages, stages, strict=True)
        if attempt.status is not StageStatus.LOCKED
    )
    if index is None:
        stage_part = "Every stage is done."
        report = next((a.report for a in reversed(stages) if a.report), None)
        instruction = _REALISTIC_CLOSING if style is InterviewerStyle.REALISTIC else _CLOSING
    else:
        stage, attempt = problem.stages[index], stages[index]
        stage_part = (
            f"Current stage prompt (the candidate sees this):\n{stage.prompt_md.strip()}\n\n"
            f"Your private notes for this stage:\n{stage.notes_md.strip()}"
        )
        report = attempt.report
        instruction = _instruction(problem, stages, index, trigger, style, signals or Signals())

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


def _text(response: Any) -> str:
    return "".join(getattr(b, "text", "") for b in response.content if b.type == "text").strip()


def interviewer_reply(
    client: anthropic.Anthropic,
    model: str,
    problem: StagedProblem,
    stages: list[StageAttempt],
    index: int | None,
    code: dict[str, str],
    chat: list[ChatMessage],
    trigger: Trigger,
    style: InterviewerStyle = InterviewerStyle.COACH,
    signals: Signals | None = None,
) -> str:
    """The interviewer's next message. A realistic reply that breaks the
    speaking rules is sent back once with what to fix; the rewrite is used
    either way (a slightly-off line beats no interviewer)."""
    prompt = build_prompt(problem, stages, index, code, chat, trigger, style, signals)
    system = REALISTIC_SYSTEM_PROMPT if style is InterviewerStyle.REALISTIC else SYSTEM_PROMPT
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    response = client.messages.create(
        model=model, max_tokens=MAX_REPLY_TOKENS, system=system, messages=cast(Any, messages)
    )
    text = _text(response)
    problems = speaking_problems(text, style, closing=index is None) if text else []
    if problems:
        messages += [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": "Rewrite that reply, keeping its point, and fix this:\n- "
                + "\n- ".join(problems)
                + "\nReply with the new message only.",
            },
        ]
        retry = client.messages.create(
            model=model, max_tokens=MAX_REPLY_TOKENS, system=system, messages=cast(Any, messages)
        )
        text = _text(retry) or text
    if not text:
        raise InterviewerError("The interviewer had nothing to say. Try again.")
    return text
