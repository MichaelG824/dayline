'use client';

import { useEffect, useState } from 'react';
import {
  Application,
  ImportableEvent,
  Interview,
  PREP_CATEGORIES,
  connectCalendar,
  createApplication,
  createInterview,
  deleteInterview,
  getCalendarStatus,
  getImportableCalendarEvents,
  importCalendarEvent,
  syncInterviewsToCalendar,
} from '../lib/api';
import { categoryMeta } from '../lib/categories';
import { daysUntil, formatDateTimeLabel } from '../lib/dates';

interface Props {
  interviews: Interview[];
  applications: Application[];
  onChanged: () => void;
}

function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

function InterviewCard({ interview, onDelete }: { interview: Interview; onDelete: () => void }) {
  const meta = categoryMeta(interview.category);
  const days = daysUntil(interview.scheduledAt);
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center font-mono text-sm text-zinc-900 dark:text-zinc-100">
            {initials(interview.company ?? '??')}
          </div>
          <div>
            <p className="font-semibold text-zinc-900 dark:text-zinc-100">{interview.company}</p>
            <p className="text-sm text-zinc-500">{formatDateTimeLabel(interview.scheduledAt)}</p>
          </div>
        </div>
        <button onClick={onDelete} className="text-zinc-400 dark:text-zinc-600 hover:text-zinc-700 dark:hover:text-zinc-300 px-2">
          &times;
        </button>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-xs font-mono px-2 py-1 rounded-full bg-zinc-100 dark:bg-zinc-800 ${meta.text}`}>
          &bull; {meta.short}
        </span>
        {interview.syncedToCalendar && (
          <span className="text-xs font-mono px-2 py-1 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
            &#10003; Synced
          </span>
        )}
      </div>
      {interview.notes && <p className="text-sm text-zinc-600 dark:text-zinc-400">{interview.notes}</p>}
      <span className="self-start text-sm font-mono px-3 py-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300">
        {days <= 0 ? 'today' : `${days} day${days === 1 ? '' : 's'} away`}
      </span>
    </div>
  );
}

function CalendarConnect({
  connected,
  onConnected,
  onSynced,
}: {
  connected: boolean | null;
  onConnected: () => void;
  onSynced: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncedCount, setSyncedCount] = useState<number | null>(null);

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      await connectCalendar();
      onConnected();
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

  if (connected === null) return null;

  if (connected) {
    return (
      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-4 flex items-center gap-3 flex-wrap">
        <span className="text-sm text-emerald-600 dark:text-emerald-400 font-medium">
          Google Calendar connected
        </span>
        <button
          onClick={handleSyncNow}
          disabled={busy}
          className="ml-auto px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700 disabled:opacity-40"
        >
          {busy ? 'Syncing...' : 'Sync interviews now'}
        </button>
        {syncedCount !== null && (
          <span className="text-xs text-zinc-500 basis-full">Synced {syncedCount} interview(s).</span>
        )}
        {error && <p className="text-rose-600 dark:text-rose-400 text-sm basis-full">{error}</p>}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-4 flex flex-col gap-2">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Connect Google Calendar to push your interviews there automatically. Needs a
        one-time setup - see <span className="font-mono">GOOGLE_SETUP.md</span> in the repo.
      </p>
      <button
        onClick={handleConnect}
        disabled={busy}
        className="self-start px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
      >
        {busy ? 'Waiting for sign-in...' : 'Connect Google Calendar'}
      </button>
      {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}
    </div>
  );
}

interface ImportDraft {
  company: string;
  category: string;
}

function ImportFromCalendar({ connected, onImported }: { connected: boolean | null; onImported: () => void }) {
  const [events, setEvents] = useState<ImportableEvent[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ImportDraft>>({});
  const [importingId, setImportingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!connected) {
      setEvents([]);
      return;
    }
    getImportableCalendarEvents()
      .then((items) => {
        setEvents(items);
        setDrafts((prev) => {
          const next = { ...prev };
          for (const item of items) {
            if (!next[item.eventId]) {
              next[item.eventId] = { company: item.suggestedCompany, category: PREP_CATEGORIES[0] };
            }
          }
          return next;
        });
      })
      .catch(() => setEvents([]));
  }, [connected]);

  function updateDraft(eventId: string, patch: Partial<ImportDraft>) {
    setDrafts((prev) => ({ ...prev, [eventId]: { ...prev[eventId], ...patch } }));
  }

  async function handleImport(item: ImportableEvent) {
    const draft = drafts[item.eventId] ?? { company: item.suggestedCompany, category: PREP_CATEGORIES[0] };
    setImportingId(item.eventId);
    setError(null);
    try {
      await importCalendarEvent({
        eventId: item.eventId,
        start: item.start,
        company: draft.company.trim() || item.suggestedCompany,
        category: draft.category,
      });
      setEvents((prev) => prev.filter((e) => e.eventId !== item.eventId));
      onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import event');
    } finally {
      setImportingId(null);
    }
  }

  if (!connected || events.length === 0) return null;

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-4 flex flex-col gap-3">
      <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
        Found on your calendar - import as an interview?
      </p>
      <div className="flex flex-col gap-2">
        {events.map((item) => {
          const draft = drafts[item.eventId] ?? { company: item.suggestedCompany, category: PREP_CATEGORIES[0] };
          return (
            <div key={item.eventId} className="flex items-center gap-2 flex-wrap">
              <input
                value={draft.company}
                onChange={(e) => updateDraft(item.eventId, { company: e.target.value })}
                className="flex-1 min-w-[10rem] bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-1.5 text-sm"
              />
              <span className="text-xs text-zinc-500 font-mono shrink-0">
                {formatDateTimeLabel(item.start)}
              </span>
              <select
                value={draft.category}
                onChange={(e) => updateDraft(item.eventId, { category: e.target.value })}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-2 py-1.5 text-sm"
              >
                {PREP_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <button
                onClick={() => handleImport(item)}
                disabled={importingId === item.eventId}
                className="px-3 py-1.5 text-xs rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40 shrink-0"
              >
                {importingId === item.eventId ? 'Importing...' : 'Import'}
              </button>
            </div>
          );
        })}
      </div>
      {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}
    </div>
  );
}

export function InterviewsTab({ interviews, applications, onChanged }: Props) {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [company, setCompany] = useState('');
  const [role, setRole] = useState('');
  const [applicationId, setApplicationId] = useState('');
  const [category, setCategory] = useState<string>(PREP_CATEGORIES[0]);
  const [scheduledAt, setScheduledAt] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCalendarStatus()
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!scheduledAt) return;
    setSubmitting(true);
    setError(null);
    try {
      let appId = applicationId;
      if (!appId) {
        if (!company.trim() || !role.trim()) {
          setError('Pick an existing company or enter a new company + role.');
          setSubmitting(false);
          return;
        }
        const app = await createApplication({ company: company.trim(), role: role.trim() });
        appId = app.id;
      }
      await createInterview({
        applicationId: appId,
        category,
        scheduledAt: new Date(scheduledAt).toISOString(),
        notes: notes.trim() || undefined,
      });
      onChanged();
      setShowForm(false);
      setCompany('');
      setRole('');
      setApplicationId('');
      setScheduledAt('');
      setNotes('');
    } catch {
      setError('Could not add interview - is the API running on :8000?');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string, company: string | null) {
    if (!confirm(`Delete the ${company ?? 'this'} interview? This also removes its Google Calendar event and cannot be undone.`)) {
      return;
    }
    await deleteInterview(id);
    onChanged();
  }

  return (
    <div className="flex flex-col gap-6">
      <CalendarConnect
        connected={connected}
        onConnected={() => setConnected(true)}
        onSynced={onChanged}
      />
      <ImportFromCalendar connected={connected} onImported={onChanged} />

      <div className="flex justify-end">
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 text-sm rounded-lg bg-amber-500/90 hover:bg-amber-400 text-black font-medium"
        >
          + Interview
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {interviews.map((i) => (
          <InterviewCard key={i.id} interview={i} onDelete={() => handleDelete(i.id, i.company)} />
        ))}
      </div>
      {interviews.length === 0 && <p className="text-zinc-500 text-sm">None scheduled.</p>}

      {showForm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-6 w-full max-w-md">
            <h2 className="text-lg font-semibold mb-4 text-zinc-900 dark:text-zinc-100">Add an interview</h2>
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <select
                value={applicationId}
                onChange={(e) => setApplicationId(e.target.value)}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">New company...</option>
                {applications.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.company} - {a.role}
                  </option>
                ))}
              </select>
              {!applicationId && (
                <div className="grid grid-cols-2 gap-3">
                  <input
                    placeholder="Company"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
                  />
                  <input
                    placeholder="Role"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              )}
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
              >
                {PREP_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
              />
              <input
                placeholder="Notes (optional)"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
              />
              {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}
              <div className="flex justify-end gap-2 mt-2">
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2 text-sm text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !scheduledAt}
                  className="px-4 py-2 text-sm rounded-lg bg-amber-500/90 hover:bg-amber-400 text-black font-medium disabled:opacity-40"
                >
                  {submitting ? 'Adding...' : 'Add interview'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
