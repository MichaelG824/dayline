# Google Calendar setup

`GoogleCalendarClient` talks to your real Google Calendar - today it powers
interview auto-discovery only (section 4). Task blocks are deliberately kept
out of your real calendar entirely - they're Dayline's own scheduling detail,
not something meant to clutter your actual calendar. It needs a one-time
OAuth setup below (this is the part only you can do).

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

## 4. Interviews auto-discovered from your calendar (live today)

Once steps 1-3 above are done, open the app's Interviews tab and click
**Connect Google Calendar** - it runs the OAuth consent flow (steps 3 above
happen in a browser window the backend opens) and writes `token.json`. From
then on:

**The calendar is the source of truth for interviews - there's no import
step.** Every event on your calendar automatically shows up as a tracked
interview (company guessed from the title, category defaulted to your
current top-ranked prep category - both editable in place). Moving an
interview's time on Google Calendar is picked up automatically the next
time the tab loads - that's the entire reschedule mechanism, no edit screen
needed. A false positive (a personal call, a duplicate entry) can be
dismissed with the "x" button without ever touching the real event - it just
won't be tracked in Dayline anymore, and it's reversible from the "Hidden"
section. An interview you create with `+ Interview` while connected pushes a
new event to your calendar and *that* one Dayline will fully delete if you
remove it, since it made it.

This is wired into `api/main.py`'s `/api/calendar/*` and `/api/interviews`
endpoints. Tasks are entirely separate and never touch your real calendar at
all - by design, not as a deferred step (see section 5).

## 5. Tasks stay entirely in-app (deliberate, not deferred)

Task blocks are never written to a real calendar, and this isn't a gap to
fill in later - it's the chosen design. Tasks are Dayline's own scheduling
detail (what to work on, for how long, in what order); the user's real
calendar is for external commitments like interviews. The day-scheduling
calendar (`api/main.py`'s `_calendar()`) stays `InMemoryCalendar` per day for
this same reason, not because reading real busy time from your calendar is
technically hard - if you want that anyway, you can wire it in yourself:

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
