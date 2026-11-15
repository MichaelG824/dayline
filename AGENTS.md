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
- **Hidden tests never touch the workspace tree**: the runner's `POST /sandboxes/{id}/hidden-tests` copies them into the ignored `.dayline/hidden` folder for one run and runs the pack's `hidden_test_cmd` (python, rails and next-nest have one). A stage passes only when the whole cumulative run (active + passed stages, never skipped ones) passes and every one of its own tests ran.
- **Scores are computed in code** (`staged.score_round`): edge cases are "hit" only if they passed the stage's first run; design churn is the share of the previous stage's code lines kept (`REWRITE_THRESHOLD`). The interviewer (`mock/interviewer.py`, `MOCK_MODEL`) only talks; it never changes round state. Notes, hidden tests, and locked stages never reach the client (`serializers.staged_round_json`).
- Changing `sandbox/` (packs included) means re-running `deploy/sandbox-vm/setup.sh`; an older runner answers hidden-test runs with a 501 "redeploy" error.

## In-session AI assistant (AI-assisted live rounds)

Live sessions whose template or staged problem has `round_type = "AI-assisted project"` get a coding assistant (`mock/assistant.py`, wired in `api/services/mock_assistant.py`; `services/mock.assistant_enabled` decides).
Model: `MOCK_ASSISTANT_MODEL`, default `claude-sonnet-4-5` on purpose (the captain's choice, not a stale default).

- **No mode writes.** Ask and plan get read-only tools; edit adds `propose_edit`, which only drafts a full new file plus the version it was based on. The only write is `POST .../assistant/edits/{id}` with `accept`, through `mock_live.write_file`, and only if the file is still at that version (otherwise the edit is recorded as `conflict`).
- **The conversation lives in `mock_session_events`** (`assistant_prompt` / `assistant_response` / `assistant_edit_proposed` / `assistant_edit_decided`; shapes in the module docstring), so no migration and it survives restarts. The model gets earlier turns back as text only. `serializers.mock_event_json` strips the proposed file content; `worklog.ai_log` is the grader's compact view.
- A turn in flight is tracked in process memory (one per session) for cancelling; the client also drops the connection after a grace period, which the stream records as stopped.
- Opt-in real-model test: `RUN_MODEL_TESTS=1 uv run pytest tests/test_mock_assistant_model.py`.

## Full-stack packs and the live preview (Mock tab)

`sandbox/packs/{rails,next-nest}` declare dev servers (`[[servers]]`; the `pack.toml` format is at the top of `dayline_runner/packs.py`). The runner supervises them (`servers.py`) and serves them through its preview proxy (`preview.py`); the Workspace's Preview pane (`web/app/components/mock/PreviewPane.tsx`) shows them.

- Sandboxes keep `network_mode: none`: each preview connection is a `docker exec` of `socat` inside the sandbox (`tunnel.py`), so a pack with servers needs `socat` in its image.
- `/api/preview/<session>/<token>/<port>/...` is a capability URL. The app is served with a CSP `sandbox` (opaque origin) so it can never act on Dayline's origin, which also means it sends no cookies: that path skips the auth gate and Dayline's CORS middleware on purpose, Dayline answers the app's CORS preflights, and the runner keeps the app's cookies in a per-sandbox jar (`cookies.py`). Previewed apps cannot use `localStorage` or `document.cookie`. See `api/services/mock_preview.py`.
- Apps serve under `$BASE_PATH` (Next `basePath`, Rails `config.ru` `map`); a server with `base_path = false` (the Nest API) is served from `/` and the proxy strips the prefix.
- `[dependencies]` is the allowed list, checked both ways against the pack's lockfile at load. Generated projects must pass `deps.project_problems` (runner `POST /packs/{name}/check`, adapter `check_dependencies`); `create` refuses projects that do not.
- Editor saves are copied into place by a process inside the sandbox (`manager.write_file`), so dev-server file watchers fire under gVisor as well as runc.
- Pins with reasons: `@swc/core` 1.16.2 (later releases unpack a native addon into a writable, executable folder), TypeScript 6 (swc-node cannot load TS 7), Next needs `turbopack: { root: '/' }` (dependencies live in the image), and Minitest 6 no longer autoloads plugins, so the Rails test commands preload `lib/dayline_junit.rb`.
- The in-session assistant reads the dev servers' logs (`get_server_logs`) through `mock_preview.server_logs_reader`; it is offered only when the pack runs servers. In the Workspace the assistant and the preview share the right side: both open on 2xl screens, otherwise the one opened last.
- Per-pack `ignore` keeps build output and databases (`.next`, Rails `tmp`/`log`/`storage`) out of the file tree and snapshots; per-pack `memory` raises the sandbox limit (next-nest: 1.5 GiB). VM sizing for these packs is in `deploy/sandbox-vm/README.md`.

## Generated full-stack rounds (Mock tab)

The candidate describes a round (plus optional text context files) and Dayline generates a Rails or Next.js + NestJS project, validates it in a real sandbox, and lets them preview it before starting an AI-assisted staged round in it (stage 1 = the task, stage 2 = the change request).

- `mock/project_spec.py` (inputs, the `Artifact`, the rules code enforces), `mock/project_gen.py` (the model writes on top of the `notes-board-*` template scaffold via `submit_project`, then fixes via `revise_project`; at most `MAX_REPAIRS` repairs), `mock/project_check.py` (deps, boot + preview, visible tests, each stage's hidden tests fail before and pass after its reference). Nothing unvalidated is ever handed over. Model: `MOCK_GENERATOR_MODEL` (default `claude-sonnet-5-5`).
- Projects live in `mock_generated_projects` (migration 015), per owner (the signed-in email). A round started from one is an ordinary staged session whose `staged_problem_id` is the project id, so always resolve problems through `api/services/staged_problems.find_problem`, never `builtin_staged_problems()` directly.
- Generated stages match JUnit cases by the `(classname, name)` pairs validation recorded (`Stage.cases`): Vitest and Minitest classnames are not pytest module names.
- Generation runs in a worker thread (`api/services/mock_generate.py`) and keeps its state on the row (progress, attempt log, token usage). The client follows it with a long poll, which also keeps a scale-to-zero host's CPU allocated; a row untouched for `STALE_AFTER` reads as failed. One generation per user at a time.
- Validation and preview sandboxes count against the runner's `SANDBOX_MAX_RUNNING`; starting a round destroys the project's preview sandbox (`gen-<id>`) first.
- Docker tests: `RUN_DOCKER_TESTS=1 uv run pytest tests/test_project_gen_docker.py` (fixture projects in `tests/generated_projects/`); add `RUN_MODEL_TESTS=1` for the real-model `tests/test_project_gen_model.py`.

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
