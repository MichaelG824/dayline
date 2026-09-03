# Google Calendar setup

`GoogleCalendarClient` writes the planner's time blocks to your real Google
Calendar. It needs a one-time OAuth setup (this is the step only you can do).

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

## 4. Use it in the pipeline

Swap it in for `InMemoryCalendar` (`api/main.py`'s `_calendar()` currently
constructs `InMemoryCalendar` per day - replace that with a single
module-level `GoogleCalendarClient()` once you've completed the setup above):

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
