"""An eval of the realistic interviewer against the real model
(``MOCK_MODEL``, default Claude Sonnet 5.5): scripted candidate messages
that pressure it ("just tell me if this is right", "write it for me", "was
that good?") and the change request's delivery.

Each reply must pass the coded speaking rules (no praise, no confirming
correctness, no code, short), and a judge (``MOCK_GRADER_MODEL``) answers a
yes/no question per case about what the reply did.

Opt in with ``RUN_MODEL_TESTS=1`` (needs Anthropic credentials; costs a few
cents).
"""

from __future__ import annotations

import os
from datetime import timedelta

import anthropic
import pytest

from dayline.mock import grader_model, mock_model
from dayline.mock.interviewer import (
    ChatMessage,
    Signals,
    Trigger,
    interviewer_reply,
    speaking_problems,
)
from dayline.mock.staged import new_round
from dayline.models import InterviewerStyle, StageAttempt, StageStatus
from tests.round_fixture import PROBLEM, T0

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1 to run"
)

CODE = {
    "api/src/notes/notes.service.ts": """import { Injectable } from '@nestjs/common';

@Injectable()
export class NotesService {
  private notes: { id: number; title: string; tags: string[] }[] = [];

  create(title: string, tags: string[] = []) {
    const note = { id: this.notes.length + 1, title, tags: tags.map((t) => t.trim()) };
    this.notes.push(note);
    return note;
  }

  list() {
    return [...this.notes].reverse();
  }
}
""",
}

# (candidate message, signals, judge question that must be answered YES)
CASES: list[tuple[str, Signals, str]] = [
    (
        "I think it's done. Just tell me if this is right.",
        Signals(),
        "Does the reply avoid saying whether the code is correct, and instead ask how the "
        "candidate would check it (for example with a test or by trying it)?",
    ),
    (
        "Can you just write the normalise function for me?",
        Signals(),
        "Does the reply decline to write the code or give the solution?",
    ),
    (
        "Is my solution correct? Yes or no.",
        Signals(),
        "Does the reply avoid answering yes or no about correctness?",
    ),
    (
        "OK I added the tags. Was that good?",
        Signals(),
        "Does the reply avoid praising or reassuring the candidate?",
    ),
    (
        "Should tags be case-insensitive, so 'Work' and 'work' are the same tag?",
        Signals(),
        "Does the reply answer the requirements question directly (or say it is the "
        "candidate's call) rather than dodging it?",
    ),
    (
        "I'm stuck, I don't know where tags get lowercased.",
        Signals(asked_for_help=True, failing_runs=3),
        "Does the reply give at most a small nudge about where to look, without writing the "
        "code or spelling out the fix?",
    ),
]


def _judge(client: anthropic.Anthropic, reply: str, question: str) -> tuple[bool, str]:
    response = client.messages.create(
        model=grader_model(),
        max_tokens=300,
        system="You judge an interviewer's reply in a mock coding interview. Answer the "
        "question with YES or NO on the first line, then one sentence why.",
        messages=[{"role": "user", "content": f"Reply:\n<reply>{reply}</reply>\n\n{question}"}],
    )
    text = "".join(getattr(b, "text", "") for b in response.content).strip()
    return text.upper().startswith("YES"), text


def _reply(
    client: anthropic.Anthropic,
    trigger: Trigger,
    stages: list[StageAttempt],
    index: int,
    chat: list[ChatMessage],
    signals: Signals,
) -> str:
    return interviewer_reply(
        client,  # type: ignore[arg-type]
        mock_model(),
        PROBLEM,
        stages,
        index,
        CODE,
        chat,
        trigger,
        InterviewerStyle.REALISTIC,
        signals,
    )


@pytest.mark.parametrize(("message", "signals", "question"), CASES, ids=[c[0][:30] for c in CASES])
def test_the_realistic_interviewer_holds_its_line(
    message: str, signals: Signals, question: str
) -> None:
    client = anthropic.Anthropic()
    chat = [
        ChatMessage(
            "interviewer", "Hi. The task is in front of you; ask me about requirements.", 1
        ),
        ChatMessage("candidate", message, 1),
    ]
    reply = _reply(client, "message", new_round(PROBLEM, T0), 0, chat, signals)
    assert "```" not in reply, reply
    assert speaking_problems(reply, InterviewerStyle.REALISTIC) == [], reply
    passed, why = _judge(client, reply, question)
    assert passed, f"{reply}\n--- judge: {why}"


def test_the_change_request_is_delivered_briefly_in_its_own_words() -> None:
    client = anthropic.Anthropic()
    stages = new_round(PROBLEM, T0)
    stages[0].status = StageStatus.PASSED
    stages[1].status, stages[1].started_at = StageStatus.ACTIVE, T0 + timedelta(minutes=25)
    chat = [ChatMessage("interviewer", "Hi. The task is in front of you.", 1)]
    reply = _reply(client, "stage_start", stages, 1, chat, Signals())
    assert speaking_problems(reply, InterviewerStyle.REALISTIC) == [], reply
    assert "tag" in reply.lower(), reply  # Its own words: "filter" is not required.
    passed, why = _judge(
        client,
        reply,
        "Does the reply deliver a new product requirement (filtering notes by a tag) the way "
        "an interviewer interrupts a candidate, without suggesting how to implement it?",
    )
    assert passed, f"{reply}\n--- judge: {why}"
