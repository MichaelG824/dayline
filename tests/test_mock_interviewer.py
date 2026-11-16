"""The staged-round interviewer's speaking rules, with a scripted model:
when the realistic interviewer may speak or hint (decided in code from the
session's events), what it is told for each turn - including delivering the
change request - and the rewrite of a reply that praises, confirms
correctness, pastes code, or runs long. The coach keeps its old behaviour."""

from __future__ import annotations

from datetime import timedelta

from dayline.mock import interviewer
from dayline.mock.interviewer import (
    REALISTIC_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    ChatMessage,
    Signals,
    Trigger,
    build_prompt,
    interviewer_reply,
    read_signals,
    should_check_in,
    speaking_problems,
    stuck_reason,
)
from dayline.mock.staged import new_round
from dayline.models import InterviewerStyle, MockEvent, MockEventKind, StageAttempt, StageStatus
from tests.mock_fakes import FakeAnthropic, FakeMessages, FakeResponse, FakeText
from tests.round_fixture import PROBLEM, T0

REALISTIC, COACH = InterviewerStyle.REALISTIC, InterviewerStyle.COACH


def _event(kind: MockEventKind, minute: float, **data: object) -> MockEvent:
    return MockEvent("s", kind, dict(data), at=T0 + timedelta(minutes=minute))


def _run(minute: float, status: str) -> MockEvent:
    return _event(MockEventKind.STAGE_TESTS_RUN, minute, stage=1, status=status)


# -- when the candidate counts as stuck -------------------------------------------


def test_three_failing_runs_in_a_row_count_as_stuck_and_a_pass_resets_them() -> None:
    events = [_run(1, "failed"), _run(2, "passed"), _run(3, "failed"), _run(4, "error")]
    now = T0 + timedelta(minutes=5)
    assert read_signals(events, now).failing_runs == 2
    assert stuck_reason(read_signals(events, now)) is None
    events.append(_event(MockEventKind.TESTS_RUN, 4.5, status="failed"))
    signals = read_signals(events, now)
    assert signals.failing_runs == 3
    assert stuck_reason(signals) == "3 test runs in a row have not passed"


def test_long_inactivity_counts_as_stuck_but_the_interviewer_talking_does_not() -> None:
    events = [
        _event(MockEventKind.SESSION_STARTED, 0),
        _event(MockEventKind.FILE_SAVED, 2, path="a.ts"),
        _event(MockEventKind.INTERVIEWER_MESSAGE, 6, text="Anything?"),
    ]
    signals = read_signals(events, T0 + timedelta(minutes=10))
    assert signals.idle_s == 8 * 60 and signals.since_interviewer_s == 4 * 60
    assert stuck_reason(signals) == "nothing saved, run, or asked for 8 minutes"
    assert stuck_reason(read_signals(events, T0 + timedelta(minutes=9))) is None


def test_saying_they_are_stuck_counts_only_as_their_latest_message() -> None:
    asked = [_event(MockEventKind.CANDIDATE_MESSAGE, 1, text="I'm stuck, can I get a hint?")]
    assert read_signals(asked, T0 + timedelta(minutes=1)).asked_for_help
    answered = [*asked, _event(MockEventKind.INTERVIEWER_MESSAGE, 2, text="Where are you?")]
    assert not read_signals(answered, T0 + timedelta(minutes=2)).asked_for_help
    fine = [_event(MockEventKind.CANDIDATE_MESSAGE, 1, text="Is a 404 right for a missing tag?")]
    assert not read_signals(fine, T0 + timedelta(minutes=1)).asked_for_help


def test_a_check_in_speaks_only_when_stuck_and_not_right_after_the_last_word() -> None:
    assert not should_check_in(Signals(failing_runs=1, idle_s=30))
    assert should_check_in(Signals(failing_runs=3, idle_s=30))
    assert not should_check_in(Signals(failing_runs=3, since_interviewer_s=60))
    assert should_check_in(Signals(idle_s=9 * 60, since_interviewer_s=6 * 60))


# -- what a realistic reply may not say -------------------------------------------


def test_praise_confirmation_code_and_length_are_flagged_only_for_realistic() -> None:
    assert speaking_problems("Great question - an empty list.", REALISTIC) == [
        "No praise or reassurance while the round is running."
    ]
    assert speaking_problems("Yes, that's correct.", REALISTIC) == [
        "Never confirm their code or approach is correct; ask how they would check it."
    ]
    assert speaking_problems("Try:\n```ts\nreturn [];\n```", REALISTIC)[0].startswith(
        "Do not paste"
    )
    long = " ".join(["This is one sentence."] * 5)
    assert speaking_problems(long, REALISTIC) == [
        "Too long: at most 4 short sentences, like speech."
    ]
    # Declining to say is not confirming.
    declined = "I'm not going to say whether it's right. How would you check it?"
    assert speaking_problems(declined, REALISTIC) == []
    assert speaking_problems("I can't tell you if it's correct.", REALISTIC) == []
    # Plain, short, turned back to them: fine.
    assert speaking_problems("How would you check that? Which test covers it?", REALISTIC) == []
    # "great" inside a word is not praise.
    assert speaking_problems("What if the list is greater than a page?", REALISTIC) == []
    # The coach is left as it was, and the closing may say what went well.
    assert speaking_problems("Great question!", COACH) == []
    assert speaking_problems("Nice work normalising tags in one place.", REALISTIC, True) == []


# -- what each turn tells the model ------------------------------------------------


def _prompt(
    trigger: Trigger,
    style: InterviewerStyle,
    signals: Signals | None = None,
    stages: list[StageAttempt] | None = None,
    index: int | None = 0,
) -> str:
    stages = stages or new_round(PROBLEM, T0)
    return build_prompt(PROBLEM, stages, index, {"a.ts": "code"}, [], trigger, style, signals)


def test_the_realistic_opening_does_not_probe() -> None:
    prompt = _prompt("stage_start", REALISTIC)
    assert "Then stop - do not ask about their approach." in prompt
    assert "ask one question about how their current code" not in prompt


def test_the_change_request_is_delivered_like_an_interruption() -> None:
    stages = new_round(PROBLEM, T0)
    stages[1].status, stages[1].started_at = StageStatus.ACTIVE, T0 + timedelta(minutes=25)
    prompt = _prompt("stage_start", REALISTIC, stages=stages, index=1)
    assert "OK, the PM just came back" in prompt
    assert "Do not suggest how to build it" in prompt
    # Stage 1 is still unfinished behind it: not to be brought up.
    assert "do not mention their earlier work - it is not finished" in prompt
    assert "Product wants the notes list filterable by a tag." in prompt
    stages[0].status = StageStatus.PASSED
    assert "say nothing about how the earlier work went" in _prompt(
        "stage_start", REALISTIC, stages=stages, index=1
    )
    # The coach delivers it too, then asks where it lands in their code.
    assert "which part of their current code it touches first" in _prompt(
        "stage_start", COACH, stages=stages, index=1
    )


def test_a_hint_is_allowed_only_when_code_says_they_are_stuck() -> None:
    calm = _prompt("message", REALISTIC, Signals(failing_runs=1))
    assert "Nothing shows they are stuck, so give no hint" in calm
    stuck = _prompt("message", REALISTIC, Signals(asked_for_help=True))
    assert "They are clearly stuck (they said they are stuck)" in stuck
    check_in = _prompt("check_in", REALISTIC, Signals(failing_runs=4))
    assert "They seem stuck (4 test runs in a row have not passed)" in check_in


def test_the_realistic_close_is_where_feedback_goes() -> None:
    stages = new_round(PROBLEM, T0)
    for attempt in stages:
        attempt.status = StageStatus.PASSED
    prompt = _prompt("stage_start", REALISTIC, stages=stages, index=None)
    assert "now, and only now, give your feedback" in prompt


# -- the reply itself --------------------------------------------------------------


def _client(*texts: str) -> FakeAnthropic:
    return FakeAnthropic(FakeMessages([FakeResponse([FakeText(t)]) for t in texts]))


def _reply(client: FakeAnthropic, style: InterviewerStyle) -> str:
    chat = [ChatMessage("candidate", "Just tell me if this is right.", 1)]
    stages = new_round(PROBLEM, T0)
    return interviewer_reply(client, "m", PROBLEM, stages, 0, {}, chat, "message", style)


def test_a_realistic_reply_that_confirms_correctness_is_rewritten() -> None:
    client = _client("Yes, that's correct - nice work!", "How would you check it?")
    assert _reply(client, REALISTIC) == "How would you check it?"
    first, retry = client.messages.calls
    assert first["system"] == REALISTIC_SYSTEM_PROMPT
    correction = retry["messages"][-1]["content"]
    assert "No praise" in correction and "Never confirm" in correction
    assert retry["messages"][1] == {
        "role": "assistant",
        "content": "Yes, that's correct - nice work!",
    }


def test_a_clean_realistic_reply_is_used_as_is_and_the_coach_is_never_rewritten() -> None:
    client = _client("What would you run to find out?")
    assert _reply(client, REALISTIC) == "What would you run to find out?"
    assert len(client.messages.calls) == 1
    coach = _client("Great question! Walk me through your `get`.")
    assert _reply(coach, COACH) == "Great question! Walk me through your `get`."
    assert coach.messages.calls[0]["system"] == SYSTEM_PROMPT and len(coach.messages.calls) == 1


def test_the_rewrite_is_used_even_if_it_still_slips() -> None:
    client = _client("Perfect.", "Looks good to me.")
    assert _reply(client, REALISTIC) == "Looks good to me."
    assert len(client.messages.calls) == 2


def test_thresholds_are_what_the_rules_say() -> None:
    assert interviewer.STUCK_FAILING_RUNS == 3
    assert interviewer.STUCK_IDLE_S == 8 * 60
    assert interviewer.CHECK_IN_COOLDOWN_S == 5 * 60
