# Google Calendar setup

`GoogleCalendarClient` talks to your real Google Calendar - today it powers
interview sync and a best-effort push of your planned task blocks (section
4); using the real calendar as the planner's own *busy-time source* is a
separate, still-deferred step (section 5). Either way it needs the same
one-time OAuth setup below (this is the part only you can do).

## 1. Install the extra

```bash
pip install '.[google]'
```

## 2. Create a Google OAuth client

1. Go to the [Google Cloud Console](https://console.cloud.google.com/), create
   (or pick) a project.
2. Enable the **Google Calendar API** for that project
   (APIs & Services → Library → Google Calendar API → Enable).
3. Configure the **OAuth consent screen** (External is fine for personal use;
   add your own Google account as a test user).
4. Create credentials → **OAuth client ID** → application type **Desktop app**.
5. Download the JSON and save it as **`credentials.json`** in the repo root.

## 3. First run: consent once

The first time `GoogleCalendarClient` is constructed it opens a browser, you
grant access, and it writes **`token.json`** next to `credentials.json`. After
that it refreshes silently - no more prompts.

```python
from dayline.adapters.calendar import GoogleCalendarClient
cal = GoogleCalendarClient()          # opens the consent flow on first use
```

Both `credentials.json` and `token.json` are secrets - keep them out of git
(they should be gitignored).

## 4. Interview and task sync (live today)

Once steps 1-3 above are done, open the app's Calendar tab and click
**Connect Google Calendar** - it runs the OAuth consent flow (steps 3 above
happen in a browser window the backend opens) and writes `token.json`. From
then on:

- Every interview you create pushes to your real Google Calendar
  automatically, and deleting an interview removes its calendar event too.
  Use **Sync interviews now** to backfill anything created before you
  connected. (`adapters/interview_calendar_sync.py`.)
- Every time the day's plan is computed - page load, day navigation, task
  edits, or the chat assistant reallocating time and you applying its
  proposal - today's planned task blocks are also pushed to your real
  calendar as `[dayline] <task>` events, reconciled the same idempotent way
  the in-memory scheduling calendar already is (`scheduler.run.sync_plan_to_calendar`).
  This is a one-way, best-effort mirror: it never blocks or fails a plan
  request if Google is briefly unreachable.

Both are wired into `api/main.py`'s `/api/calendar/*` and `/api/plan`
endpoints. Neither changes what the day-scheduling calendar below reads busy
time from or plans against - the planner itself keeps using the fast,
reliable in-memory calendar; only its already-computed result gets mirrored
out.

## 5. Using the real calendar as the planner's busy-time source (still deferred)

The day-scheduling calendar (`api/main.py`'s `_calendar()`) still constructs
`InMemoryCalendar` per day - having the *planner itself* read busy time from
and plan directly against your real calendar (rather than mirroring an
already-computed plan to it, as section 4 does) is a separate, bigger change:
every `POST /api/plan` call would become network-dependent, so any Google
hiccup would break viewing or editing tasks even though that has nothing to
do with Google. Remains manual/deferred. Swap it in yourself if you want it:

```python
from dayline.adapters.task_source import SupabaseTaskSource
from dayline.adapters.calendar import GoogleCalendarClient
from dayline.adapters.supabase_client import get_supabase_client
from dayline.scheduler.run import run_daily_plan
from datetime import date

run_daily_plan(date.today(), SupabaseTaskSource(get_supabase_client()), GoogleCalendarClient())
```

The planner reads your busy time, plans around it, and writes marker-tagged
blocks (`[dayline] ...`) it can safely re-create on the next run.

## Options

```python
GoogleCalendarClient(
    calendar_id="primary",     # or a specific calendar id
    timezone="America/New_York",  # defaults to the calendar's own timezone
)
```
