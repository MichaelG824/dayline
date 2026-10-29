'use client';

import { useState } from 'react';
import { CategoryWeight, deleteTask, updateTask } from '../lib/api';
import { categoryMeta, formatDuration, isMiscCategory, rankCategories } from '../lib/categories';
import { formatClockTime } from '../lib/dates';
import { DayTask } from '../lib/dayTasks';
import { TaskFormModal } from './TaskFormModal';

interface Props {
  day: string;
  dayTasks: DayTask[];
  categoryWeights: CategoryWeight[];
  loading: boolean;
  onTasksChanged: () => void;
  onOpenProblem: (problemId: string) => void;
}

function TaskRow({
  task,
  onToggle,
  onEdit,
  onDelete,
  onOpenProblem,
}: {
  task: DayTask;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onOpenProblem: (problemId: string) => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40">
      <input
        type="checkbox"
        checked={task.status === 'Done'}
        onChange={onToggle}
        className="w-4 h-4 accent-indigo-500 cursor-pointer"
      />
      <span className={`flex-1 ${task.status === 'Done' ? 'line-through text-zinc-400 dark:text-zinc-500' : 'text-zinc-900 dark:text-zinc-100'}`}>
        {task.name}
      </span>
      <span className="font-mono text-sm text-zinc-500">
        {task.effectiveTime ? `${formatClockTime(task.effectiveTime)} · ` : ''}
        {formatDuration(task.estDurationMin)}
      </span>
      {task.problemId && (
        <button
          onClick={() => onOpenProblem(task.problemId!)}
          title="Open problem"
          className="font-mono text-xs text-rose-600 dark:text-rose-400 hover:text-rose-500 dark:hover:text-rose-300 px-1"
        >
          &lt;/&gt;
        </button>
      )}
      <button
        onClick={onEdit}
        title="Edit"
        className="text-zinc-400 dark:text-zinc-600 hover:text-zinc-700 dark:hover:text-zinc-300 px-1"
      >
        &#9998;
      </button>
      <button
        onClick={onDelete}
        title="Delete"
        className="text-zinc-400 dark:text-zinc-600 hover:text-rose-500 dark:hover:text-rose-400 px-1"
      >
        &times;
      </button>
    </div>
  );
}

export function TasksTab({
  day,
  dayTasks,
  categoryWeights,
  loading,
  onTasksChanged,
  onOpenProblem,
}: Props) {
  const [modal, setModal] = useState<{ defaultCategory?: string; task?: DayTask } | null>(null);

  async function toggleDone(task: DayTask) {
    await updateTask(task.id, { status: task.status === 'Done' ? 'Backlog' : 'Done' });
    onTasksChanged();
  }

  async function handleDelete(task: DayTask) {
    if (!confirm(`Delete "${task.name}"? This also removes it from your Google Calendar.`)) {
      return;
    }
    await deleteTask(task.id);
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
                <TaskRow
                  key={t.id}
                  task={t}
                  onToggle={() => toggleDone(t)}
                  onEdit={() => setModal({ task: t })}
                  onDelete={() => handleDelete(t)}
                onOpenProblem={onOpenProblem}
                />
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
              <TaskRow
                key={t.id}
                task={t}
                onToggle={() => toggleDone(t)}
                onEdit={() => setModal({ task: t })}
                onDelete={() => handleDelete(t)}
                onOpenProblem={onOpenProblem}
              />
            ))}
          </div>
        </section>
      )}

      {dayTasks.length === 0 && !loading && (
        <p className="text-zinc-500 text-sm">Nothing planned for this day yet.</p>
      )}

      {modal && (
        <TaskFormModal
          day={day}
          defaultCategory={modal.defaultCategory}
          task={modal.task}
          onClose={() => setModal(null)}
          onSaved={onTasksChanged}
        />
      )}
    </div>
  );
}
