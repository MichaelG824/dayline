# dayline

A personal planning agent that turns a task list into a **time-blocked daily plan** - centered on job-search interview prep (AI coding, behavioral, system design, Leetcode) with everyday errands slotted underneath at lower priority.

Tasks, applications, and upcoming interviews persist in Supabase.
Day-scheduling stays in-memory; interviews can sync to Google Calendar (see `GOOGLE_SETUP.md`).
A private **Mock** tab holds an interview question bank (paste a 1point3acres post, in any language, and review the questions it extracts), your rubrics and grading standards, and a grader that scores a mock transcript with quoted evidence; weak areas become prep tasks through the same confirm step as chat.
It also runs **staged practical rounds**: you code in a sandbox while an agent interviewer adds production follow-ups to your own code, stage by stage (an LRU cache gains a TTL, then sizes, then threads), with hidden tests gating each stage and a per-stage summary of time, design churn, and edge cases.
A chat panel is **analysis-first** (plan, backlog + interviews, outcomes/retros): it advises by default and only proposes concrete changes when you ask or a fix is clearly needed. Mutations always stay propose → multi-select confirm → apply (never auto-apply). Planner preferences and a lightweight outcome log feed the assistant; see `AGENTS.md` and `api/chat.py`.

## Architecture

One deterministic planning core sits underneath the FastAPI + Next.js dashboard:

```
   FastAPI + Next.js ──▶  build_plan()  ──▶  Plan (blocks + unplaced + brief)
                              ▲                       │
                              │                       ▼ write-back
              TaskSource (Protocol)         CalendarClient (Protocol)
                ├ InMemoryTaskSource (tests)   └ InMemoryCalendar (run today;
                └ SupabaseTaskSource (wired,       Google Calendar deferred)
                    the real backend)
```

`ApplicationSource` and `InterviewSource` follow the same pattern (`InMemory*` for tests, `Supabase*` as the real backend).
The FastAPI layer (`src/dayline/api/main.py`) is a thin JSON surface over the same core: it calls `run_daily_plan`, resolves category-priority defaults and interview-proximity bumps *before* the pure core ever sees a task list, and serializes the result for the Next.js frontend (`web/`) to fetch and render.
No scheduling logic lives in either layer.

The core and scheduler depend **only** on the adapter Protocols, never a concrete Supabase/Google class, so a different real adapter can drop in unchanged.

## Directory layout

```
dayline/
  pyproject.toml
  README.md
  .env.example              # Supabase, Anthropic, Google sign-in, AUTH_SECRET
  .gitignore
  src/dayline/
    models.py               # Task, Application, Interview, TimeSlot, ScheduledBlock, Plan + enums
    planner/core.py         # build_plan(tasks, free_slots, day) - pure & deterministic
    adapters/
      task_source.py        # TaskSource Protocol + InMemoryTaskSource + SupabaseTaskSource
      application_source.py # ApplicationSource Protocol + InMemory/Supabase implementations
      interview_source.py   # InterviewSource Protocol + InMemory/Supabase implementations
      category_weights.py   # category -> default-priority mapping (plain functions, not a Protocol)
      calendar.py            # CalendarClient Protocol + InMemoryCalendar (+ deferred GoogleCalendarClient)
      supabase_client.py     # shared Supabase client construction
    scheduler/run.py        # run_daily_plan(...) - wiring, idempotent write-back, interview-proximity bump
    api/
      main.py                # FastAPI JSON surface - thin layer over the core
      auth.py                # Google sign-in + ALLOWED_EMAIL gate
      chat.py                 # analysis-first LLM chat (read tools + propose/confirm)
    adapters/
      preferences.py         # planner preference memory (Supabase + in-memory)
      outcomes.py            # lightweight outcome log for retros
  web/                       # Next.js dashboard - fetches api/main.py, renders
  supabase/
    schema.sql               # base schema
    migrations/              # run in order; includes 009_planner_preferences_outcomes.sql
  tests/
    test_planner_core.py    # every planning-core rule
    test_scheduler_run.py   # end-to-end + idempotency + interview-proximity bump
    fixtures.py
```

## Planning rules (in `planner/core.py`)

`build_plan(tasks, free_slots, day)` is a pure, deterministic function (no I/O, no Supabase, no category-weight resolution):

1. **Anchor** every `fixed_time` task at its time; it never overlaps a busy event or another anchored task (a collision is reported, not overlapped).
2. **Pack** the rest into free slots by **priority** (P0 first), honoring `preferred_window` when a fitting slot exists there, then best duration fit.
3. Job-search **prep** categories (the two AI-coding variants, behavioral, system design, Leetcode) outrank `Errand`/`Other` on priority ties.
4. Placed blocks never overlap busy events or each other (zero collisions).
5. Tasks that don't fit are returned in `unplaced` (never dropped).
6. A short human-readable `brief` lists the ordered blocks and what didn't fit.

Two things happen *before* a task list reaches `build_plan()`, never inside it:

- **Category focus weighting** - a new task's default `Priority` is resolved from the `category_weights` table (`adapters/category_weights.py`) when one isn't given explicitly; re-ranking the table alone never touches existing tasks.
- **Interview-proximity priority bump** - a task linked to an interview within 3 days gets its *effective* priority bumped one level for that planning run only (never persisted), so prep work naturally wins scarce time as the interview approaches.

**Idempotency** (in `scheduler/run.py`): every agent-created calendar block is titled with a stable `[dayline] ` marker.
Each run deletes its own prior blocks for the day before re-planning, so re-running reconciles to the same plan with no duplicates.

## Setup

Requires **Python 3.12** locally (pinned in `.python-version`; production Docker stays on `python:3.12-slim` with `pip`).

```bash
uv sync --extra dev --extra google   # creates .venv, installs core + google extra + pytest/ruff/mypy/debugpy
cp .env.example .env                 # fill in Supabase, Anthropic, AUTH_SECRET, Google OAuth client
```

The planning core and adapter Protocols are stdlib-only and need no credentials to build or test.
The API (`api/main.py`) does need `.env` populated for live adapters (Supabase, Anthropic) and for Google sign-in (`AUTH_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).
The `google` extra backs `GoogleCalendarClient` (see `GOOGLE_SETUP.md`) and is not needed for sign-in.

### Supabase setup

1. Create a project at [supabase.com](https://supabase.com).
2. In the SQL Editor, run `supabase/schema.sql` in its own query.
3. Then run `supabase/migrations/002_dayline_features.sql` in a separate query.
4. Then run `supabase/migrations/003_seed_category_weights.sql` in a third, separate query.

5. Run every later migration (`004_...` onward, including `011_mock_interviews.sql`) in order, each in its own query.
   `013_staged_rounds.sql` and `014_seed_staged_rubric.sql` must be separate runs for the same reason as steps 3 and 4.

Steps 3 and 4 must be separate runs - Postgres refuses to let a newly added enum value be used in the same transaction that added it, so combining them fails with `unsafe use of new value`.

Copy the **Project URL** and the **secret key** (Settings → API Keys; not the publishable key - this backend needs to bypass row-level security, which only the secret key can do) into `.env`.

## Run the tests

```bash
uv run pytest          # unit tests for every core rule + end-to-end idempotency + interview-proximity bump
uv run ruff check .    # lint
uv run mypy            # type-check (config in pyproject.toml)
```

## Sample end-to-end run (against the fakes)

Stands in for a future morning cron - no network, no credentials:

```bash
uv run python -m dayline.scheduler.run
# or:
uv run dayline
```

It seeds a realistic scenario (a fixed Leetcode contest, prep tasks, an errand, and a pre-existing "Team standup" event), runs the pipeline, and prints the brief.

## Sign-in

Dayline is locked to one Google account, proven with Google sign-in (not a typed email).
Set `ALLOWED_EMAIL` to the one Google account that may use the app.
Every `/api/*` route except `/api/health` and `/api/auth/*` returns 401 when logged out and 403 when signed in as anyone else.
The Next.js UI sends the session cookie on every `web/app/lib/api.ts` fetch (`credentials: 'include'`).

Create a Google Cloud **Web application** OAuth client (not the Calendar desktop client).
Authorized JavaScript origin: `PUBLIC_URL`.
Authorized redirect URI: `{PUBLIC_URL}/api/auth/callback`.
Put the client id/secret and a stable `AUTH_SECRET` in `.env`.

## Run the dashboard locally (FastAPI + Next.js)

Two processes, in separate terminals:

```bash
# Terminal 1 - API (reads .env). Cursor/VS Code: Run and Debug → "Dayline API (chat)"
# (no --reload: the reloader forks a child and breakpoints miss)
uv run uvicorn dayline.api.main:app --port 8000

# Terminal 2 - UI (rewrites /api/* to the API so the browser stays same-origin)
cd web
npm install   # first time only
npm run dev
```

Open http://localhost:3000 (or :3003/:3004 if 3000 is taken).
Logged-out visitors see the sign-in screen, not the planner.
The dashboard shows a day picker, the plan, unplaced tasks, a brief, task editing, category ranking, interviews, and chat.
"Re-plan" re-runs the scheduler and re-renders, demonstrating idempotency (no duplicate blocks).
All logic lives in the core/scheduler/adapters.
`api/main.py` only calls interfaces and serializes JSON, and `web/` only fetches and renders.

## Production (one URL, sleeps when idle)

The production shape is one container (`Dockerfile`).
Caddy reverse-proxies Next.js and FastAPI on a single origin so cookies stay simple.
Chat (`POST /api/chat`) needs a host whose request timeout can cover an Anthropic round-trip (minutes, not a 10s hobby function).

Preferred host: **Cloud Run** with `--min-instances=0` and `--timeout=300`.
Allow unauthenticated Cloud Run IAM so the login page is reachable; Dayline's Google allowlist is the actual lock.
Render (`render.yaml`) also spins down from GitHub.
Use Starter or higher there (free is a 30s timeout).

Captain steps after this repo is on GitHub:

1. Create the Google **Web application** OAuth client above.
2. Pick Cloud Run or Render, deploy the `Dockerfile`, and set env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`, `AUTH_SECRET`, `ALLOWED_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_URL` (the `https://...` service URL).
3. Add `{PUBLIC_URL}/api/auth/callback` to the OAuth client's redirect URIs (and `{PUBLIC_URL}` as an authorized JavaScript origin).
4. Optional interviews-on-calendar: set `GOOGLE_CALENDAR_REFRESH_TOKEN` (see `GOOGLE_SETUP.md`).
   The desktop `credentials.json` flow does not survive scale-to-zero.
5. Optional live mock sessions: run `deploy/sandbox-vm/setup.sh`, then `deploy/sandbox-vm/connect-cloud-run.sh` (see `deploy/sandbox-vm/README.md`).

### Sandbox runner host

Live mock sessions execute untrusted code, so the sandbox runner (`sandbox/runner`) does not run in the Cloud Run container.
It runs alone on one e2-small Compute Engine VM (about $14/month) in a dedicated VPC with no public address and no service account, and every session container runs under gVisor.
Cloud Run reaches it over Direct VPC egress at a private IP (`SANDBOX_RUNNER_URL`), authenticated with `SANDBOX_RUNNER_SECRET` from Secret Manager; the runner port accepts connections only from Cloud Run's egress subnet.
Without these two env vars, live sessions show "sandbox unavailable" and everything else works.
`deploy/sandbox-vm/README.md` has the resources, security posture, and the idempotent setup and teardown scripts.

Do not put a public URL in front of the API until sign-in is configured.
A local production-shaped run is `docker compose up --build` on http://localhost:8080.

## Deferred / out of scope

- Production Google Calendar still needs a one-time refresh token in env (`GOOGLE_SETUP.md`).
  Connect in the Interviews tab is the local desktop flow.
- OS-level cron/launchd installation for an unattended morning run.
