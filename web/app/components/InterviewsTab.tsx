'use client';

import { useState } from 'react';
import {
  Application,
  Interview,
  PREP_CATEGORIES,
  createApplication,
  createInterview,
  deleteInterview,
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
      <span className={`self-start text-xs font-mono px-2 py-1 rounded-full bg-zinc-100 dark:bg-zinc-800 ${meta.text}`}>
        &bull; {meta.short}
      </span>
      {interview.notes && <p className="text-sm text-zinc-600 dark:text-zinc-400">{interview.notes}</p>}
      <span className="self-start text-sm font-mono px-3 py-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300">
        {days <= 0 ? 'today' : `${days} day${days === 1 ? '' : 's'} away`}
      </span>
    </div>
  );
}

export function InterviewsTab({ interviews, applications, onChanged }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [company, setCompany] = useState('');
  const [role, setRole] = useState('');
  const [applicationId, setApplicationId] = useState('');
  const [category, setCategory] = useState<string>(PREP_CATEGORIES[0]);
  const [scheduledAt, setScheduledAt] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function handleDelete(id: string) {
    await deleteInterview(id);
    onChanged();
  }

  return (
    <div className="flex flex-col gap-6">
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
          <InterviewCard key={i.id} interview={i} onDelete={() => handleDelete(i.id)} />
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
