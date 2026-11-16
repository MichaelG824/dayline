"""Timed stages arrive by the server's clock.

A generated round's change request unlocks at its minute into the round
(``mock/staged.py``, ``Stage.unlock_min``). Nothing runs in the background:
every read of a round in progress first unlocks whatever is due, stamped with
the minute it was due, so a reload, a closed tab, or a skewed client clock
never moves it. The client only uses the time to know when to ask again.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dayline.api.context import AppContext
from dayline.mock import staged
from dayline.mock.staged import StagedProblem
from dayline.models import MockEvent, MockEventKind, MockSession, MockSessionStatus


def catch_up(
    ctx: AppContext, session: MockSession, problem: StagedProblem, now: datetime | None = None
) -> None:
    """Unlock every timed stage that is due, save the round, and record a
    ``stage_unlocked`` event at the moment each arrived."""
    if session.status is not MockSessionStatus.LIVE or session.started_at is None:
        return
    unlocked = staged.unlock_due(
        problem, session.stages, session.started_at, now or datetime.now(UTC)
    )
    if not unlocked:
        return
    ctx.mock_source.update_session(session)
    for index in unlocked:
        ctx.mock_source.add_event(
            MockEvent(
                session_id=session.id,
                kind=MockEventKind.STAGE_UNLOCKED,
                data={"stage": index + 1, "early": False},
                at=session.stages[index].started_at,
            )
        )
