'use client';

import { useState } from 'react';
import { CategoryWeight, updateTask } from '../lib/api';
import { categoryMeta, formatDuration, isMiscCategory, rankCategories } from '../lib/categories';
import { formatClockTime } from '../lib/dates';
import { DayTask } from '../lib/dayTasks';
import { AddTaskModal } from './AddTaskModal';

interface Props {
  day: string;
  dayTasks: DayTask[];
  categoryWeights: CategoryWeight[];
  loading: boolean;
  onTasksChanged: () => void;
}

function TaskRow({ task, onToggle }: { task: DayTask; onToggle: () => void }) {
  return (
    <label className="flex items-center gap-3 px-4 py-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 cursor-pointer">
      <input
        type="checkbox"
        checked={task.status === 'Done'}
        onChange={onToggle}
        className="w-4 h-4 accent-indigo-500"
      />
      <span className={`flex-1 ${task.status === 'Done' ? 'line-through text-zinc-400 dark:text-zinc-500' : 'text-zinc-900 dark:text-zinc-100'}`}>
        {task.name}
      </span>
      <span className="font-mono text-sm text-zinc-500">
        {task.effectiveTime ? `${formatClockTime(task.effectiveTime)} · ` : ''}
        {formatDuration(task.estDurationMin)}
      </span>
    </label>
  );
}

export function TasksTab({ day, dayTasks, categoryWeights, loading, onTasksChanged }: Props) {
  const [modal, setModal] = useState<{ defaultCategory?: string } | null>(null);

  async function toggleDone(task: DayTask) {
    await updateTask(task.id, { status: task.status === 'Done' ? 'Backlog' : 'Done' });
    onTasksChanged();
  }

  const rankedCategories = rankCategories(categoryWeights);
  const miscTasks = dayTasks.filter((t) => isMiscCategory(t.category));

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <div className="flex justify-end gap-2">
        <button
          onClick={() => setModal({ defaultCategory: 'Errand' })}
          className="px-4 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
        >
          + Misc
        </button>
        <button
          onClick={() => setModal({})}
          className="px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white"
        >
          + Task
        </button>
      </div>

      {loading && <p className="text-sm text-zinc-500">Re-planning...</p>}

      {rankedCategories.map((category, i) => {
        const tasks = dayTasks.filter((t) => t.category === category);
        if (tasks.length === 0) return null;
        const meta = categoryMeta(category);
        return (
          <section key={category}>
            <h2 className={`font-mono text-sm mb-2 ${meta.text}`}>
              <span className="text-zinc-400 dark:text-zinc-600">&bull;</span> #{i + 1} &mdash; {meta.short.toUpperCase()}
            </h2>
            <div className="flex flex-col gap-2">
              {tasks.map((t) => (
                <TaskRow key={t.id} task={t} onToggle={() => toggleDone(t)} />
              ))}
            </div>
          </section>
        );
      })}

      {miscTasks.length > 0 && (
        <section>
          <h2 className="font-mono text-sm mb-2 text-zinc-500">
            <span className="text-zinc-400 dark:text-zinc-600">&bull;</span> MISCELLANEOUS
          </h2>
          <div className="flex flex-col gap-2">
            {miscTasks.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={() => toggleDone(t)} />
            ))}
          </div>
        </section>
      )}

      {dayTasks.length === 0 && !loading && (
        <p className="text-zinc-500 text-sm">Nothing planned for this day yet.</p>
      )}

      {modal && (
        <AddTaskModal
          day={day}
          defaultCategory={modal.defaultCategory}
          onClose={() => setModal(null)}
          onCreated={onTasksChanged}
        />
      )}
    </div>
  );
}
