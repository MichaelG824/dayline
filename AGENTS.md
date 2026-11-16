# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Architecture invariants (do not break)

- The planning core (`src/dayline/planner/core.py`) and scheduler (`scheduler/run.py`) must depend **only** on the adapter Protocols in `adapters/` - never a concrete Supabase/Google class. Real adapters drop in behind `TaskSource` / `CalendarClient` / `ApplicationSource` / `InterviewSource`.
- Keep the core and adapter interfaces **stdlib-only** (dataclasses/enum). `category_weights.py` is a deliberate exception to the Protocol pattern (plain functions, not a Protocol + adapter pair) - it's simple CRUD on one small table that never feeds `build_plan`, so a full Protocol there would be over-engineering.
- The UI is the `src/dayline/api/` FastAPI layer + `web/` (Next.js) - both are thin layers with no scheduling logic. The API layer is split: `api/main.py` is an app factory only (create `FastAPI`, CORS, auth gate, `include_router`); `api/controllers/*.py` are HTTP-only `APIRouter`s (path, status codes, request models); `api/services/*.py` hold the orchestration that talks to adapters/planner; `api/serializers.py` turns `Plan`/`Task`/`Application`/`Interview` into the JSON the client consumes; `api/parsing.py` holds the string->enum parsers that raise `HTTPException` 400. Shared singletons (Supabase sources, day-keyed `InMemoryCalendar`s, the optional `GoogleCalendarClient`, the Anthropic client) live on one `AppContext` in `api/context.py`, injected into controllers via the `ContextDep` `Annotated[..., Depends]` alias. `web/` only fetches and renders.
- Main navigation lives in the sidebar (`web/app/components/SidebarNav.tsx`; below `lg` the sidebar is a drawer opened from `AppShell`'s menu bar). The UI labels the `problems` tab "LeetCode Problems" and the `mock` tab "AI / Practical Programming"; "Problems tab" / "Mock tab" in these notes and the code mean those.
- `build_plan(tasks, free_slots, day)` is pure and deterministic (no I/O, no Supabase, no category-weight resolution). Rules and their tests are in `README.md` and `tests/test_planner_core.py`. Category-priority resolution and the interview-proximity priority bump both happen *before* `build_plan()` sees the task list (in `api/services/tasks.py` and `scheduler/run.py` respectively) - never inside it.
- Idempotency hinges on the `AGENT_MARKER` title prefix in `scheduler/run.py`: runs delete their own prior marker-tagged blocks before re-planning. See `tests/test_scheduler_run.py`. The FastAPI `/api/plan` endpoint calls this on every request (including "Re-plan" clicks), so it reconciles rather than duplicates.

## Job funnel, Supabase, and interview tracking

`Application` (`models.py`) is the job-search funnel entity (company, role, stage). `Interview` is a separate entity (not just `Application.next_interview_at`) since one company can have multiple rounds of different types at different times - `Task.interview_id` optionally links a task to a specific interview, and `scheduler/run.py`'s `_bump_for_interview_proximity` bumps that task's *effective* priority one level (never persisted) when the interview is within `INTERVIEW_PROXIMITY_DAYS` (3). `Task.application_id` also exists for the coarser "this task preps for this company generally" link.

Supabase (`SupabaseTaskSource`, `SupabaseApplicationSource`, `SupabaseInterviewSource` in `adapters/`) is the real, wired persistent backend - `api/context.py` constructs the shared `AppContext` (holding these sources) lazily on first `get_context()`, not day-keyed fakes. `supabase/schema.sql` + `supabase/migrations/` are the Postgres schema (source of truth: `models.py` - keep them in sync by hand). Migrations must run in order in the Supabase SQL Editor; `002_dayline_features.sql` and `003_seed_category_weights.sql` must be **separate runs** - Postgres refuses to let a new enum value (added via `ALTER TYPE ... ADD VALUE`) be used in the same transaction that added it, so a script combining both will fail with `unsafe use of new value`.

The day-scheduling calendar stays in-memory (`InMemoryCalendar`, day-keyed) and task blocks are never written to a real calendar - that's deliberate, not deferred: tasks are Dayline's own scheduling detail, and the user chose to keep them out of their real calendar entirely (only interviews belong there). `GoogleCalendarClient` (`adapters/calendar.py`) is wired live for interviews only. `AppContext.google_calendar` (`api/context.py`) holds it as an optional singleton (the only mutable field): it starts from `GOOGLE_CALENDAR_REFRESH_TOKEN` when that env is set, otherwise `None` until `POST /api/calendar/connect` (desktop OAuth, in `api/services/calendar.py`). The connect/status controls live in `web/`'s Interviews tab, not a separate calendar tab (there isn't one - keeping the connect UI next to the interviews it mainly serves avoided a mostly-redundant surface). Production scale-to-zero hosts must use the refresh-token env; `token.json` does not survive spin-down.

**Interviews: the calendar is the source of truth, not Supabase.** `GET /api/interviews` runs `reconcile_calendar_interviews()` (`api/services/interviews.py`) before every read: any calendar event in the discovery window with no linked `Interview` row gets one auto-created (company guessed via `adapters/interview_calendar_sync.guess_company_from_title`, category defaulted to the current #1-ranked prep category) - there is no manual "import" step. An already-linked interview's `scheduled_at` is refreshed from the live event every time, which is also the entire reschedule mechanism: moving the event on Google Calendar is picked up automatically, with no edit endpoint needed. Company and category are set once and never overwritten, so a user's correction survives. `Interview.google_event_owned` records whether Dayline created that calendar event (via `+ Interview` while connected) or merely discovered/links to one that already existed; `delete_interview` uses it to decide behavior - owned interviews get a real delete (row + calendar event, via `adapters/interview_calendar_sync.py`'s `sync_interview_event`, which updates an existing linked event in place via `events().patch()` rather than delete-and-recreate, since a discovered interview's event was never Dayline's to destroy), while a non-owned interview is only ever hidden (`Interview.hidden`, excluded from `list_upcoming()` and from rediscovery, reversible via `POST /api/interviews/{id}/unhide`) - the real calendar event is never touched.

## Category focus weighting

The 5 prep categories (`AI_CODING_REACT_PYTHON`, `AI_CODING_DSA`, `BEHAVIORAL`, `SYSTEM_DESIGN`, `LEETCODE`) each have a default `Priority` stored in the `category_weights` Supabase table (`adapters/category_weights.py`). New tasks created without an explicit priority resolve it from this table; re-ranking the table alone never touches existing tasks - `POST /api/category-weights/apply` is the explicit, separate action that bulk-reprioritizes `BACKLOG` tasks only (never `SCHEDULED`/`DONE`).

## Auth and production host

Google sign-in is the ownership proof; `ALLOWED_EMAIL` is the only account that may use the app (`api/auth.py`). If it is unset, nobody is allowlisted.
Unauthenticated `/api/*` calls 401; a valid session for any other email 403.
`/api/health`, `/api/auth/*` and the token-authenticated `/api/preview/*` stay public.
The Next.js middleware (`web/middleware.ts`) is UX only (login / not-allowed screens); FastAPI is the hard gate.
Browser fetches in `web/app/lib/api.ts` send the session cookie (`credentials: 'include'`).

Production is one container (`Dockerfile` + Caddy) so the UI and API share an origin.
Prefer Cloud Run `--min-instances=0 --timeout=300` so the service sleeps when idle and chat is not killed by a 10s hobby timeout.
`AUTH_SECRET` must be stable across cold starts.
Do not put a public URL in front of the API until Google OAuth env is set.
The production sandbox runner lives on its own private GCE VM, not in the Cloud Run container (`deploy/sandbox-vm/README.md`); a Cloud Run deploy never updates it, so re-run `deploy/sandbox-vm/setup.sh` after changing `sandbox/`.
Cloud Run traffic on `dayline` is pinned to named revisions (not "latest"), so a new revision gets 0% until `gcloud run services update-traffic`; read the new revision from `status.latestCreatedRevisionName` (`latestReadyRevisionName` can lag).

## Commands

- Backend local install: `uv sync --extra dev --extra google` (Python 3.12 via `.python-version`; lockfile `uv.lock`). Requires a populated `.env` (see `.env.example`) to run the API - the pure core/scheduler/tests do not need it. Auth tests (`tests/test_auth.py`) do not need live Supabase. Checks: `uv run pytest`, `uv run ruff check .`, `uv run mypy`. Sample run: `uv run python -m dayline.scheduler.run`. API: `uv run uvicorn dayline.api.main:app --port 8000` (no `--reload`; Cursor/VS Code launch config `.vscode/launch.json` "Dayline API (chat)" attaches debugpy). Production Docker still uses `pip` / `python:3.12-slim`.
- Frontend: `cd web && npm install && npm run dev` (http://localhost:3000; Next rewrites `/api/*` to :8000).

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
