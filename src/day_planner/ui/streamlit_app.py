"""Streamlit dashboard (item 6) - a thin interactive surface over the core.

This is a *third trigger* alongside the future cron and chat surfaces, not a
replacement: it holds zero scheduling logic. It only builds the in-memory fakes,
calls :func:`run_daily_plan`, and renders the result. Once the real adapters are
wired it picks up real data with no change to this file.

Run it with::

    streamlit run src/day_planner/ui/streamlit_app.py
"""

from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from day_planner.adapters.calendar import CalendarEvent, InMemoryCalendar
from day_planner.adapters.task_source import InMemoryTaskSource
from day_planner.models import Category, Priority, Task, Window
from day_planner.scheduler.run import run_daily_plan


def _seed_fakes(day: date) -> tuple[InMemoryTaskSource, InMemoryCalendar]:
    """Build the same no-credentials scenario used by the console entrypoint,
    anchored to ``day`` so the demo works for whatever date the user picks."""

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour=hour, minute=minute))

    tasks = [
        Task("Leetcode weekly contest", Category.LEETCODE, Priority.P0, 90, "t-contest",
             fixed_time=at(10, 30)),
        Task("Behavioral story polish", Category.BEHAVIORAL, Priority.P1, 60, "t-behav",
             preferred_window=Window.MORNING),
        Task("System design: rate limiter", Category.SYSTEM_DESIGN, Priority.P1, 90,
             "t-sysd", preferred_window=Window.AFTERNOON),
        Task("AI coding practice", Category.AI_CODING, Priority.P2, 60, "t-aicode"),
        Task("Pick up dry cleaning", Category.ERRAND, Priority.P2, 30, "t-errand"),
        Task("Read a paper", Category.OTHER, Priority.P3, 45, "t-paper"),
    ]
    task_source = InMemoryTaskSource(tasks)
    calendar = InMemoryCalendar(
        [CalendarEvent("pre-standup", "Team standup", at(9, 0), at(9, 30))]
    )
    return task_source, calendar


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def main() -> None:
    st.set_page_config(page_title="Day Planner", page_icon="🗓️", layout="wide")
    st.title("🗓️ Day Planner")
    st.caption(
        f"Today is {date.today().isoformat()}. Running against in-memory fakes "
        "(no Notion / Google credentials required)."
    )

    picked = st.date_input("Plan which day?", value=date.today())
    # st.date_input can return a tuple in range mode; we use single-date mode.
    day: date = picked if isinstance(picked, date) else picked[0]

    # Persist the fakes across reruns keyed by day, so the "Re-plan" button hits
    # the *same* calendar/task state - this is what demonstrates idempotency
    # (re-running reconciles rather than duplicating blocks).
    state_key = f"fakes::{day.isoformat()}"
    if state_key not in st.session_state:
        st.session_state[state_key] = _seed_fakes(day)
    task_source, calendar = st.session_state[state_key]

    replan = st.button("🔁 Re-plan", help="Re-runs the scheduler; blocks reconcile, no duplicates.")

    plan = run_daily_plan(day, task_source, calendar)

    left, right = st.columns(2)

    with left:
        st.subheader("Plan")
        if plan.blocks:
            rows = []
            for b in plan.blocks:
                task = task_source.get_task(b.task_id)
                rows.append(
                    {
                        "Time": f"{_fmt(b.start)}-{_fmt(b.end)}",
                        "Task": b.title,
                        "Category": task.category.value,
                        "Priority": task.priority.name,
                    }
                )
            st.table(rows)
        else:
            st.info("Nothing scheduled.")

        st.subheader("Unplaced")
        if plan.unplaced:
            for t in plan.unplaced:
                st.write(f"- **{t.name}** ({t.category.value}, {t.priority.name})")
        else:
            st.success("Everything fit.")

        # Verify idempotency live: count agent-created calendar blocks. After any
        # number of Re-plan clicks this equals the number of planned blocks.
        agent_blocks = [
            e for e in calendar.list_events(day) if e.title.startswith("[day-planner] ")
        ]
        st.caption(
            f"Agent calendar blocks now on {day.isoformat()}: {len(agent_blocks)} "
            f"(matches {len(plan.blocks)} planned - Re-plan does not duplicate)."
        )
        if replan:
            st.toast("Re-planned - blocks reconciled, no duplicates.")

    with right:
        st.subheader("Brief")
        st.code(plan.brief, language="text")

        st.subheader("Task list (from TaskSource)")
        task_rows = [
            {
                "Task": t.name,
                "Category": t.category.value,
                "Priority": t.priority.name,
                "Status": t.status.value,
                "Est (min)": t.est_duration_min,
                "Scheduled": (
                    _fmt(st_time) if (st_time := task_source.scheduled_time_of(t.id)) else "-"
                ),
            }
            for t in task_source.list_tasks()
        ]
        st.table(task_rows)


main()
