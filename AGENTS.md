# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Architecture invariants (do not break)

- The planning core (`src/day_planner/planner/core.py`) and scheduler (`scheduler/run.py`) must depend **only** on the adapter Protocols in `adapters/` - never a concrete Notion/Google class. Real adapters drop in behind `TaskSource` / `CalendarClient`.
- Keep the core and adapter interfaces **stdlib-only** (dataclasses/enum). `streamlit` is the sole runtime dep and is a thin UI layer - no scheduling logic in `ui/`.
- `build_plan(tasks, free_slots, day)` is pure and deterministic (no I/O). Rules and their tests are in `README.md` and `tests/test_planner_core.py`.
- Idempotency hinges on the `AGENT_MARKER` title prefix in `scheduler/run.py`: runs delete their own prior marker-tagged blocks before re-planning. See `tests/test_scheduler_run.py`.

## Deferred (no credentials yet)

- `NotionTaskSource` / `GoogleCalendarClient` raise `NotImplementedError` on purpose. `mcp_server/` is the captain's hand-coded Notion MCP server (contract only in `mcp_server/README.md`) - do not implement it.

## Commands

- Dev install: `pip install -e '.[dev]'`. Checks: `pytest`, `ruff check .`, `mypy`. Sample run: `python -m day_planner.scheduler.run`. UI: `streamlit run src/day_planner/ui/streamlit_app.py`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
