# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Architecture invariants (do not break)

- The planning core (`src/dayline/planner/core.py`) and scheduler (`scheduler/run.py`) must depend **only** on the adapter Protocols in `adapters/` - never a concrete Supabase/Google class. Real adapters drop in behind `TaskSource` / `CalendarClient` / `ApplicationSource` / `InterviewSource`.
- Keep the core and adapter interfaces **stdlib-only** (dataclasses/enum). `category_weights.py` is a deliberate exception to the Protocol pattern (plain functions, not a Protocol + adapter pair) - it's simple CRUD on one small table that never feeds `build_plan`, so a full Protocol there would be over-engineering.
- The UI is the `src/dayline/api/` FastAPI layer + `web/` (Next.js) - both are thin layers with no scheduling logic. The API layer is split: `api/main.py` is an app factory only (create `FastAPI`, CORS, auth gate, `include_router`); `api/controllers/*.py` are HTTP-only `APIRouter`s (path, status codes, request models); `api/services/*.py` hold the orchestration that talks to adapters/planner; `api/serializers.py` turns `Plan`/`Task`/`Application`/`Interview` into the JSON the client consumes; `api/parsing.py` holds the string->enum parsers that raise `HTTPException` 400. Shared singletons (Supabase sources, day-keyed `InMemoryCalendar`s, the optional `GoogleCalendarClient`, the Anthropic client) live on one `AppContext` in `api/context.py`, injected into controllers via the `ContextDep` `Annotated[..., Depends]` alias. `web/` only fetches and renders.
- `build_plan(tasks, free_slots, day)` is pure and deterministic (no I/O, no Supabase, no category-weight resolution). Rules and their tests are in `README.md` and `tests/test_planner_core.py`. Category-priority resolution and the interview-proximity priority bump both happen *before* `build_plan()` sees the task list (in `api/services/tasks.py` and `scheduler/run.py` respectively) - never inside it.
- Idempotency hinges on the `AGENT_MARKER` title prefix in `scheduler/run.py`: runs delete their own prior marker-tagged blocks before re-planning. See `tests/test_scheduler_run.py`. The FastAPI `/api/plan` endpoint calls this on every request (including "Re-plan" clicks), so it reconciles rather than duplicates.

## Job funnel, Supabase, and interview tracking

`Application` (`models.py`) is the job-search funnel entity (company, role, stage). `Interview` is a separate entity (not just `Application.next_interview_at`) since one company can have multiple rounds of different types at different times - `Task.interview_id` optionally links a task to a specific interview, and `scheduler/run.py`'s `_bump_for_interview_proximity` bumps that task's *effective* priority one level (never persisted) when the interview is within `INTERVIEW_PROXIMITY_DAYS` (3). `Task.application_id` also exists for the coarser "this task preps for this company generally" link.

Supabase (`SupabaseTaskSource`, `SupabaseApplicationSource`, `SupabaseInterviewSource` in `adapters/`) is the real, wired persistent backend - `api/context.py` constructs the shared `AppContext` (holding these sources) lazily on first `get_context()`, not day-keyed fakes. `supabase/schema.sql` + `supabase/migrations/` are the Postgres schema (source of truth: `models.py` - keep them in sync by hand). Migrations must run in order in the Supabase SQL Editor; `002_dayline_features.sql` and `003_seed_category_weights.sql` must be **separate runs** - Postgres refuses to let a new enum value (added via `ALTER TYPE ... ADD VALUE`) be used in the same transaction that added it, so a script combining both will fail with `unsafe use of new value`.

The day-scheduling calendar stays in-memory (`InMemoryCalendar`, day-keyed) and task blocks are never written to a real calendar - that's deliberate, not deferred: tasks are Dayline's own scheduling detail, and the user chose to keep them out of their real calendar entirely (only interviews belong there). `GoogleCalendarClient` (`adapters/calendar.py`) is wired live for interviews only. `AppContext.google_calendar` (`api/context.py`) holds it as an optional singleton (the only mutable field): it starts from `GOOGLE_CALENDAR_REFRESH_TOKEN` when that env is set, otherwise `None` until `POST /api/calendar/connect` (desktop OAuth, in `api/services/calendar.py`). The connect/status controls live in `web/`'s Interviews tab, not a separate calendar tab (there isn't one - keeping the connect UI next to the interviews it mainly serves avoided a mostly-redundant surface). Production scale-to-zero hosts must use the refresh-token env; `token.json` does not survive spin-down.

**Interviews: the calendar is the source of truth, not Supabase.** `GET /api/interviews` runs `reconcile_calendar_interviews()` (`api/services/interviews.py`) before every read: any calendar event in the discovery window with no linked `Interview` row gets one auto-created (company guessed via `adapters/interview_calendar_sync.guess_company_from_title`, category defaulted to the current #1-ranked prep category) - there is no manual "import" step. An already-linked interview's `scheduled_at` is refreshed from the live event every time, which is also the entire reschedule mechanism: moving the event on Google Calendar is picked up automatically, with no edit endpoint needed. Company and category are set once and never overwritten, so a user's correction survives. `Interview.google_event_owned` records whether Dayline created that calendar event (via `+ Interview` while connected) or merely discovered/links to one that already existed; `delete_interview` uses it to decide behavior - owned interviews get a real delete (row + calendar event, via `adapters/interview_calendar_sync.py`'s `sync_interview_event`, which updates an existing linked event in place via `events().patch()` rather than delete-and-recreate, since a discovered interview's event was never Dayline's to destroy), while a non-owned interview is only ever hidden (`Interview.hidden`, excluded from `list_upcoming()` and from rediscovery, reversible via `POST /api/interviews/{id}/unhide`) - the real calendar event is never touched.

## Category focus weighting

The 5 prep categories (`AI_CODING_REACT_PYTHON`, `AI_CODING_DSA`, `BEHAVIORAL`, `SYSTEM_DESIGN`, `LEETCODE`) each have a default `Priority` stored in the `category_weights` Supabase table (`adapters/category_weights.py`). New tasks created without an explicit priority resolve it from this table; re-ranking the table alone never touches existing tasks - `POST /api/category-weights/apply` is the explicit, separate action that bulk-reprioritizes `BACKLOG` tasks only (never `SCHEDULED`/`DONE`).

## LLM chat (analysis-first, propose/confirm)

`api/chat.py` uses the Anthropic Python SDK directly (no MCP). The assistant is **analysis-first**: situation → risks/gaps → recommendation. It may stop at advice; `propose_*` tools fire only when the user asks for changes or analysis clearly needs a concrete fix. Response shape stays `{ explanation, proposals, history }` - **proposals may be empty**.

**Read tools** (auto-executed each turn): `list_tasks`, `get_plan`, `list_interviews`, `get_category_ranks`, `get_preferences`, `get_recent_outcomes`. **Propose tools** (schema-only until confirm): `propose_duration_change`, `propose_new_task`, `propose_reprioritization`, `propose_preference_update`, `propose_category_rank_change`. `POST /api/chat/confirm` is the only mutation path (user multi-select); never auto-apply because Claude called a tool. LLM never enters `build_plan`.

**Streaming** (`POST /api/chat/stream`): an additive SSE twin of `/api/chat`, which stays as the non-streaming fallback. `chat.py`'s `stream_chat_turn` mirrors `run_chat_turn` round-for-round (both share `_handle_tool_uses`), yielding `("status"|"delta"|"result", ...)`; `services/chat.py` hand-formats those as `data: <json>` frames (no `sse-starlette`) and `_json_default` converts SDK content blocks in `history`, which FastAPI's encoder does for free on the blocking path. The `Cache-Control: no-transform` header on the endpoint is load-bearing, not boilerplate: without it the Next dev proxy gzips the response and buffers the whole turn into one chunk. The Starlette `BaseHTTPMiddleware` auth gate does *not* buffer it.

**Preferences** (`adapters/preferences.py`, table `planner_preferences` via `009_planner_preferences_outcomes.sql`): peak hours, category caps, standing rules, free text - injected into the system prompt every turn; also `GET/PUT /api/preferences`.

**Outcomes** (`adapters/outcomes.py`, table `planner_outcomes`): lightweight accept/reject/completion/duration-override events for retros via `get_recent_outcomes`. Confirm logs accepts + rejects (`offered` minus applied); task PATCH logs completion/duration overrides best-effort. Nudges still require propose → confirm.

## Mock interviews (the Mock tab)

`adapters/mock_source.py` (`MockSource`, migration `011_mock_interviews.sql`) stores the private question bank, rubrics, grading standards (`mock_guidelines`), sessions, and scorecards. The LLM work lives in `src/dayline/mock/` (no FastAPI/Supabase imports); `api/services/mock.py` wires it.

- **Tool calls are not forced.** The current models reject `tool_choice` of type `tool`/`any`, so `mock/llm.py` offers the tool with `auto`, says "call it" in the system prompt, and nudges once if the reply is prose. Never reintroduce a forced `tool_choice`.
- **Code decides what to trust in a scorecard** (`mock/grader.py`): every rubric key exactly once with an integer 1-4 (invalid cards go back to the model, up to `MAX_ATTEMPTS`), the overall score is a weighted mean computed in code, and each evidence quote is matched against the transcript (`verified`) so invented quotes are flagged, not trusted.
- **Duplicates are suggestions, never merges.** `mock/ingest.py` shortlists similar canonical questions (rapidfuzz on title + prompt); the user picks "same as" on save. Copies point at a root via `canonical_id`, one level deep (`services/mock.py` `_canonical_target`).
- **Weak areas become tasks only via `POST /api/chat/confirm`.** `weak_area_proposals` emits `propose_new_task` proposals carrying `mock_session_id`; `apply_proposal` copies it onto the task. The client offers only proposals not yet added, so already-added ones are never logged as rejected.
- **Live sessions never touch Docker from Dayline.** Code runs in the separate `sandbox/runner` service (its own `pyproject.toml`; the only process with Docker access), reached by `adapters/sandbox.py` over HTTP/WebSocket via `SANDBOX_RUNNER_URL` + `SANDBOX_RUNNER_SECRET`. Templates live in `mock/templates/` (migration `012_mock_live_sessions.sql`). Runner Docker tests are opt-in: `RUN_DOCKER_TESTS=1 uv run pytest sandbox/runner/tests/test_runner_docker.py`.
- Models: `MOCK_MODEL` (extraction and the staged-round interviewer; default `claude-sonnet-5-5`) and `MOCK_GRADER_MODEL` (default `claude-opus-5-5`), see `mock/__init__.py`.

## Staged practical rounds (Mock tab)

A staged round is a live session (`kind = live`) with `MockSession.staged_problem_id` + `stages` (migrations 013, then 014 in a separate run), so files, terminal, resume, and end reuse `services/mock_live.py`; the staged parts live in `services/mock_staged.py`.

- **Problems are content, not code**: one folder per problem under `src/dayline/mock/staged_problems/<id>/` (format documented at the top of `mock/staged.py`). Adding a problem means adding a folder; `tests/test_staged_lru.py` shows how to prove each reference passes its stage and one-bug variants fail the right tests.
- **Hidden tests never touch the workspace tree**: the runner's `POST /sandboxes/{id}/hidden-tests` copies them into the ignored `.dayline/hidden` folder for one run and runs the pack's `hidden_test_cmd` (Python only so far). A stage passes only when the whole cumulative run (active + passed stages, never skipped ones) passes and every one of its own tests ran.
- **Scores are computed in code** (`staged.score_round`): edge cases are "hit" only if they passed the stage's first run; design churn is the share of the previous stage's code lines kept (`REWRITE_THRESHOLD`). The interviewer (`mock/interviewer.py`, `MOCK_MODEL`) only talks; it never changes round state. Notes, hidden tests, and locked stages never reach the client (`serializers.staged_round_json`).
- Changing `sandbox/` (packs included) means re-running `deploy/sandbox-vm/setup.sh`; an older runner answers hidden-test runs with a 501 "redeploy" error.

## Auth and production host

Google sign-in is the ownership proof; `ALLOWED_EMAIL` is the only account that may use the app (`api/auth.py`). If it is unset, nobody is allowlisted.
Unauthenticated `/api/*` calls 401; a valid session for any other email 403.
`/api/health` and `/api/auth/*` stay public.
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
