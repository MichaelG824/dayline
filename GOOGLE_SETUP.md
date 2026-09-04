# Google Calendar setup

`GoogleCalendarClient` talks to your real Google Calendar - today it powers
interview sync (section 4); writing the planner's own time blocks there is a
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

## 4. Interview sync (live today)

Once steps 1-3 above are done, open the app's Calendar tab and click
**Connect Google Calendar** - it runs the OAuth consent flow (steps 3 above
happen in a browser window the backend opens) and writes `token.json`. From
then on every interview you create pushes to your real Google Calendar
automatically, and deleting an interview removes its calendar event too. Use
**Sync interviews now** to backfill anything created before you connected.

This is a one-way, interview-only sync
(`adapters/interview_calendar_sync.py`, wired into `api/main.py`'s
`/api/calendar/*` endpoints) - it does not touch the day-scheduling calendar
below.

## 5. Scheduler wiring (still deferred)

The day-scheduling calendar (`api/main.py`'s `_calendar()`) still constructs
`InMemoryCalendar` per day - writing the *planner's* time-blocked plan to your
real calendar is a separate, bigger change (every `POST /api/plan` call would
become network-dependent) and remains manual/deferred. Swap it in yourself if
you want it:

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
