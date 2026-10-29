'use client';

import { useState } from 'react';
import {
  ALL_CATEGORIES,
  PRIORITIES,
  RECURRENCES,
  TaskRow,
  WEEKDAYS,
  createTask,
  updateTask,
} from '../lib/api';

interface Props {
  day: string;
  defaultCategory?: string;
  defaultName?: string;
  // Links a newly created task to a LeetCode problem (a practice session).
  problemId?: string;
  task?: TaskRow;
  onClose: () => void;
  onSaved: () => void;
}

function timeOf(fixedTime: string | null): string {
  if (!fixedTime) return '';
  const d = new Date(fixedTime);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function TaskFormModal({
  day,
  defaultCategory,
  defaultName,
  problemId,
  task,
  onClose,
  onSaved,
}: Props) {
  const isEditing = !!task;
  const [name, setName] = useState(task?.name ?? defaultName ?? '');
  const [category, setCategory] = useState<string>(task?.category ?? defaultCategory ?? ALL_CATEGORIES[0]);
  const [priority, setPriority] = useState(task?.priority ?? '');
  const [duration, setDuration] = useState(task?.estDurationMin ?? 60);
  const [time, setTime] = useState(timeOf(task?.fixedTime ?? null));
  const [recurs, setRecurs] = useState('');
  const [recurDay, setRecurDay] = useState<string>(WEEKDAYS[0]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      if (isEditing && task) {
        await updateTask(task.id, {
          name: name.trim(),
          category,
          priority: priority || undefined,
          estDurationMin: duration,
          fixedTime: time ? `${day}T${time}:00` : undefined,
        });
      } else {
        await createTask({
          name: name.trim(),
          category,
          estDurationMin: duration,
          priority: priority || undefined,
          plannedDate: recurs ? null : day,
          fixedTime: time ? `${day}T${time}:00` : null,
          recurs: recurs || undefined,
          recurDay: recurs === 'Weekly' ? recurDay : undefined,
          problemId: problemId ?? null,
        });
      }
      onSaved();
      onClose();
    } catch {
      setError(`Could not ${isEditing ? 'save' : 'create'} task - is the API running on :8000?`);
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold mb-4 text-zinc-900 dark:text-zinc-100">
          {isEditing ? 'Edit task' : 'Add task'}
        </h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            autoFocus
            placeholder="Task name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
          />
          <div className="grid grid-cols-2 gap-3">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
            >
              {ALL_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">Default priority</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
              <input
                type="number"
                min={1}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm w-full"
              />
              min
            </label>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              title="What time should this happen?"
              className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          {isEditing ? (
            task.recurs && (
              <p className="text-xs text-zinc-500">
                Repeats {task.recurs}
                {task.recurDay ? ` (${task.recurDay})` : ''} - not editable here.
              </p>
            )
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <select
                value={recurs}
                onChange={(e) => setRecurs(e.target.value)}
                className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">Does not repeat</option>
                {RECURRENCES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              {recurs === 'Weekly' && (
                <select
                  value={recurDay}
                  onChange={(e) => setRecurDay(e.target.value)}
                  className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm"
                >
                  {WEEKDAYS.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
          {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}
          <div className="flex justify-end gap-2 mt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !name.trim()}
              className="px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
            >
              {submitting ? 'Saving...' : isEditing ? 'Save changes' : 'Add task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
