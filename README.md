# day-planner

A personal planning agent that turns a task list into a **time-blocked daily plan** - centered on job-search prep (behavioral, AI-coding, Leetcode, system design) with everyday errands slotted underneath at lower priority.

This repository is the **first increment**: it scaffolds the whole project and implements everything that needs *no external credentials*, running end to end on in-memory fakes.
Real Notion (via a hand-coded MCP server) and Google Calendar wiring are deferred to a later task.

## Architecture

Two triggers today are planned (a morning cron and this Streamlit dashboard), and a chat surface later - all sit on top of **one** deterministic planning core:

```
   morning cron  ─┐
   Streamlit UI  ─┼─▶  build_plan()  ──▶  Plan (blocks + unplaced + brief)
   chat (later)  ─┘        ▲                       │
                           │                       ▼ write-back
              TaskSource (Protocol)        CalendarClient (Protocol)
                ├ InMemoryTaskSource         ├ InMemoryCalendar     (run today)
                └ NotionTaskSource (later)    └ GoogleCalendarClient (later)
```

The core and scheduler depend **only** on the adapter Protocols, never a concrete Notion/Google class, so the real adapters drop in unchanged.

## Directory layout

```
day-planner/
  pyproject.toml
  README.md
  .gitignore
  src/day_planner/
    models.py               # Task, TimeSlot, ScheduledBlock, Plan + enums
    planner/core.py         # build_plan(tasks, free_slots, day) - pure & deterministic
    adapters/
      task_source.py        # TaskSource Protocol + InMemoryTaskSource fake (+ deferred NotionTaskSource)
      calendar.py           # CalendarClient Protocol + InMemoryCalendar fake (+ deferred GoogleCalendarClient)
    scheduler/run.py        # run_daily_plan(...) - wiring + idempotent write-back
    ui/streamlit_app.py     # Streamlit dashboard - thin surface over the core
  mcp_server/
    README.md               # RESERVED for the captain's hand-coded Notion MCP server (contract only)
  tests/
    test_planner_core.py    # every planning-core rule
    test_scheduler_run.py   # end-to-end + idempotency against the fakes
    fixtures.py
```

## Planning rules (in `planner/core.py`)

`build_plan(tasks, free_slots, day)` is a pure, deterministic function (no I/O):

1. **Anchor** every `fixed_time` task at its time; it never overlaps a busy event or another anchored task (a collision is reported, not overlapped).
2. **Pack** the rest into free slots by **priority** (P0 first), honoring `preferred_window` when a fitting slot exists there, then best duration fit.
3. Job-search **prep** categories (behavioral, AI coding, leetcode, system design) outrank `Errand`/`Other` on priority ties.
4. Placed blocks never overlap busy events or each other (zero collisions).
5. Tasks that don't fit are returned in `unplaced` (never dropped).
6. A short human-readable `brief` lists the ordered blocks and what didn't fit.

**Idempotency** (in `scheduler/run.py`): every agent-created calendar block is titled with a stable `[day-planner] ` marker.
Each run deletes its own prior blocks for the day before re-planning, so re-running reconciles to the same plan with no duplicates.

## Setup

Requires **Python 3.11+**.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'      # core + streamlit + pytest/ruff/mypy
```

The planning core and adapter interfaces are stdlib-only; `streamlit` is the one runtime dependency (for the dashboard).
The deferred integrations live behind optional extras (`.[notion]`, `.[google]`) and are **not** needed to build or test a plan.

## Run the tests

```bash
pytest          # unit tests for every core rule + end-to-end idempotency
ruff check .    # lint
mypy            # type-check (config in pyproject.toml)
```

## Sample end-to-end run (against the fakes)

Stands in for the future morning cron - no network, no credentials:

```bash
python -m day_planner.scheduler.run
# or, after `pip install -e .`:
day-planner
```

It seeds a realistic scenario (a fixed Leetcode contest, prep tasks, an errand, and a pre-existing "Team standup" event), runs the pipeline, and prints the brief.

## Run the Streamlit dashboard

```bash
streamlit run src/day_planner/ui/streamlit_app.py
```

The dashboard shows today's date and a day picker, runs the scheduler and renders the plan (ordered blocks with times), the `unplaced` list, and the `brief`, displays the current task list from the `TaskSource`, and offers a **"Re-plan"** button that re-runs the scheduler and re-renders - demonstrating idempotency (no duplicate blocks).
All logic lives in the core/scheduler; the app only calls interfaces and renders.

## Setup checklist - what the captain must provide before the real adapters can be wired

Everything above runs today on fakes. To wire the *real* integrations later:

- [ ] **Notion integration** - create an internal integration and obtain a `NOTION_TOKEN`.
- [ ] **Shared task database** - create the greenfield Tasks DB (epic Subtask 1) and note its `NOTION_DATABASE_ID`.
- [ ] **Notion MCP server** - `mcp_server/` is **the captain's to build** (the deliberate MCP-learning piece). It exposes `list_tasks` / `get_task` / `update_task` over the Notion REST API and will back a `NotionTaskSource` that satisfies the existing `TaskSource` Protocol. See [`mcp_server/README.md`](mcp_server/README.md).
- [ ] **Google Cloud OAuth client** for Calendar - a `credentials.json` (and stored `token.json`) to back the direct `GoogleCalendarClient`.

Put secrets in `.env` / credential files (already git-ignored); never commit them.

## Deferred / out of scope for this increment

- Real Notion API calls and the MCP server implementation (`NotionTaskSource` raises `NotImplementedError`).
- Real Google Calendar API / OAuth (`GoogleCalendarClient` raises `NotImplementedError`).
- OS-level cron/launchd installation and the conversational surface.
