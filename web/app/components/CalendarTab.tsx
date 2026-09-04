'use client';

import { useEffect, useState } from 'react';
import { connectCalendar, getCalendarStatus, syncInterviewsToCalendar } from '../lib/api';

interface Props {
  onSynced: () => void;
}

export function CalendarTab({ onSynced }: Props) {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncedCount, setSyncedCount] = useState<number | null>(null);

  useEffect(() => {
    getCalendarStatus()
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(false));
  }, []);

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      await connectCalendar();
      setConnected(true);
      // Backfill anything created before the calendar was connected, so the
      // user sees their existing interviews right away.
      const { synced } = await syncInterviewsToCalendar();
      setSyncedCount(synced);
      onSynced();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect Google Calendar');
    } finally {
      setBusy(false);
    }
  }

  async function handleSyncNow() {
    setBusy(true);
    setError(null);
    try {
      const { synced } = await syncInterviewsToCalendar();
      setSyncedCount(synced);
      onSynced();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to sync interviews');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl flex flex-col gap-6">
      <div>
        <p className="text-4xl mb-4">🔑</p>
        <h2 className="text-lg font-semibold mb-2 text-zinc-900 dark:text-zinc-100">
          Google Calendar
        </h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-6">
          Push your upcoming interviews to your real Google Calendar. This is a
          one-time server-side OAuth flow (not a browser sign-in), so it needs
          a one-time setup step first.
        </p>
      </div>

      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-5">
        <ol className="list-decimal list-inside flex flex-col gap-2 text-sm text-zinc-700 dark:text-zinc-300">
          <li>
            Go to{' '}
            <span className="font-mono text-indigo-600 dark:text-indigo-300">console.cloud.google.com</span> and
            create (or pick) a project.
          </li>
          <li>Enable the Google Calendar API for that project.</li>
          <li>
            Configure the OAuth consent screen, then create an OAuth client ID
            (application type: Desktop app).
          </li>
          <li>
            Download the JSON and save it as{' '}
            <span className="font-mono text-indigo-600 dark:text-indigo-300">credentials.json</span> in the
            repo root.
          </li>
        </ol>
        <p className="text-xs text-zinc-500 mt-4">Full steps: see GOOGLE_SETUP.md in the repo.</p>
      </div>

      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-5 flex flex-col gap-3">
        {connected === null ? (
          <p className="text-sm text-zinc-500">Checking connection...</p>
        ) : connected ? (
          <>
            <p className="text-sm text-emerald-600 dark:text-emerald-400 font-medium">Connected</p>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              New interviews sync automatically. Use this to backfill any
              created before you connected.
            </p>
            <button
              onClick={handleSyncNow}
              disabled={busy}
              className="self-start px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
            >
              {busy ? 'Syncing...' : 'Sync interviews now'}
            </button>
            {syncedCount !== null && (
              <p className="text-sm text-zinc-500">Synced {syncedCount} interview(s).</p>
            )}
          </>
        ) : (
          <>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Not connected yet. Complete the setup above, then connect.
            </p>
            <button
              onClick={handleConnect}
              disabled={busy}
              className="self-start px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
            >
              {busy ? 'Waiting for sign-in...' : 'Connect Google Calendar'}
            </button>
          </>
        )}
        {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}
      </div>
    </div>
  );
}
