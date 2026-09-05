# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Architecture invariants (do not break)

- The planning core (`src/dayline/planner/core.py`) and scheduler (`scheduler/run.py`) must depend **only** on the adapter Protocols in `adapters/` - never a concrete Supabase/Google class. Real adapters drop in behind `TaskSource` / `CalendarClient` / `ApplicationSource` / `InterviewSource`.
- Keep the core and adapter interfaces **stdlib-only** (dataclasses/enum). `category_weights.py` is a deliberate exception to the Protocol pattern (plain functions, not a Protocol + adapter pair) - it's simple CRUD on one small table that never feeds `build_plan`, so a full Protocol there would be over-engineering.
- The UI is `src/dayline/api/main.py` (FastAPI) + `web/` (Next.js) - both are thin layers with no scheduling logic. `api/main.py` serializes `Plan`/`Task`/`Application`/`Interview` to JSON; `web/` only fetches and renders.
- `build_plan(tasks, free_slots, day)` is pure and deterministic (no I/O, no Supabase, no category-weight resolution). Rules and their tests are in `README.md` and `tests/test_planner_core.py`. Category-priority resolution and the interview-proximity priority bump both happen *before* `build_plan()` sees the task list (in `api/main.py` and `scheduler/run.py` respectively) - never inside it.
- Idempotency hinges on the `AGENT_MARKER` title prefix in `scheduler/run.py`: runs delete their own prior marker-tagged blocks before re-planning. See `tests/test_scheduler_run.py`. The FastAPI `/api/plan` endpoint calls this on every request (including "Re-plan" clicks), so it reconciles rather than duplicates.

## Job funnel, Supabase, and interview tracking

`Application` (`models.py`) is the job-search funnel entity (company, role, stage). `Interview` is a separate entity (not just `Application.next_interview_at`) since one company can have multiple rounds of different types at different times - `Task.interview_id` optionally links a task to a specific interview, and `scheduler/run.py`'s `_bump_for_interview_proximity` bumps that task's *effective* priority one level (never persisted) when the interview is within `INTERVIEW_PROXIMITY_DAYS` (3). `Task.application_id` also exists for the coarser "this task preps for this company generally" link.

Supabase (`SupabaseTaskSource`, `SupabaseApplicationSource`, `SupabaseInterviewSource` in `adapters/`) is the real, wired persistent backend - `api/main.py` constructs these once at module load, not day-keyed fakes. `supabase/schema.sql` + `supabase/migrations/` are the Postgres schema (source of truth: `models.py` - keep them in sync by hand). Migrations must run in order in the Supabase SQL Editor; `002_dayline_features.sql` and `003_seed_category_weights.sql` must be **separate runs** - Postgres refuses to let a new enum value (added via `ALTER TYPE ... ADD VALUE`) be used in the same transaction that added it, so a script combining both will fail with `unsafe use of new value`.

The day-scheduling calendar stays in-memory (`InMemoryCalendar`, day-keyed) and task blocks are never written to a real calendar - that's deliberate, not deferred: tasks are Dayline's own scheduling detail, and the user chose to keep them out of their real calendar entirely (only interviews belong there). `GoogleCalendarClient` (`adapters/calendar.py`) is wired live for interviews only. `api/main.py` holds it as an optional module-level singleton (`_google_calendar`, starts disconnected), constructed via `POST /api/calendar/connect` (runs OAuth); the connect/status controls live in `web/`'s Interviews tab, not a separate calendar tab (there isn't one - keeping the connect UI next to the interviews it mainly serves avoided a mostly-redundant surface).

**Interviews: the calendar is the source of truth, not Supabase.** `GET /api/interviews` runs `_reconcile_calendar_interviews()` (api/main.py) before every read: any calendar event in the discovery window with no linked `Interview` row gets one auto-created (company guessed via `adapters/interview_calendar_sync.guess_company_from_title`, category defaulted to the current #1-ranked prep category) - there is no manual "import" step. An already-linked interview's `scheduled_at` is refreshed from the live event every time, which is also the entire reschedule mechanism: moving the event on Google Calendar is picked up automatically, with no edit endpoint needed. Company and category are set once and never overwritten, so a user's correction survives. `Interview.google_event_owned` records whether Dayline created that calendar event (via `+ Interview` while connected) or merely discovered/links to one that already existed; `delete_interview` uses it to decide behavior - owned interviews get a real delete (row + calendar event, via `adapters/interview_calendar_sync.py`'s `sync_interview_event`, which updates an existing linked event in place via `events().patch()` rather than delete-and-recreate, since a discovered interview's event was never Dayline's to destroy), while a non-owned interview is only ever hidden (`Interview.hidden`, excluded from `list_upcoming()` and from rediscovery, reversible via `POST /api/interviews/{id}/unhide`) - the real calendar event is never touched.

## Category focus weighting

The 5 prep categories (`AI_CODING_REACT_PYTHON`, `AI_CODING_DSA`, `BEHAVIORAL`, `SYSTEM_DESIGN`, `LEETCODE`) each have a default `Priority` stored in the `category_weights` Supabase table (`adapters/category_weights.py`). New tasks created without an explicit priority resolve it from this table; re-ranking the table alone never touches existing tasks - `POST /api/category-weights/apply` is the explicit, separate action that bulk-reprioritizes `BACKLOG` tasks only (never `SCHEDULED`/`DONE`).

## LLM chat (propose/confirm)

`api/chat.py` uses the Anthropic Python SDK directly (no MCP - the tool-calling loop and its execution live in the same FastAPI process, so there's no client/server boundary for MCP to bridge). `list_tasks` is the only auto-executed tool; `propose_duration_change`/`propose_new_task`/`propose_reprioritization` are schema-only - their `tool_use` blocks are collected as data and returned to the frontend, never executed during the chat turn itself. `POST /api/chat/confirm` is the only code path that actually mutates tasks, driven by the user's explicit selection.

## Commands

- Backend dev install: `pip install -e '.[dev]'`. Requires a populated `.env` (see `.env.example`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`) to import `api/main.py` or run the API - the pure core/scheduler/tests do not need it. Checks: `pytest`, `ruff check .`, `mypy`. Sample run: `python -m dayline.scheduler.run`. API: `uvicorn dayline.api.main:app --reload --port 8000`.
- Frontend: `cd web && npm install && npm run dev` (http://localhost:3000, expects the API on :8000 - see `web/.env.local`).

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
