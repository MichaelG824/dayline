'use client';

import { useState } from 'react';
import { CategoryWeight, Interview, applyCategoryWeights, putCategoryWeights, signOut } from '../lib/api';
import { categoryMeta, formatDuration, isMiscCategory, rankCategories } from '../lib/categories';
import { DayTask } from '../lib/dayTasks';
import { daysUntil, formatDayLabel } from '../lib/dates';
import { ThemeToggle } from './ThemeToggle';

interface Props {
  day: string;
  dayTasks: DayTask[];
  categoryWeights: CategoryWeight[];
  interviews: Interview[];
  onNavigateDay: (delta: number) => void;
  onCategoryWeightsChanged: (next: CategoryWeight[]) => void;
  onAppliedToBacklog: () => void;
  onGoToCalendar: () => void;
}

export function Sidebar({
  day,
  dayTasks,
  categoryWeights,
  interviews,
  onNavigateDay,
  onCategoryWeightsChanged,
  onAppliedToBacklog,
  onGoToCalendar,
}: Props) {
  const [applying, setApplying] = useState(false);

  const prepTasks = dayTasks.filter((t) => !isMiscCategory(t.category));
  const miscTasks = dayTasks.filter((t) => isMiscCategory(t.category));

  const prepTotalMin = prepTasks.reduce((sum, t) => sum + t.estDurationMin, 0);
  const prepDoneMin = prepTasks
    .filter((t) => t.status === 'Done')
    .reduce((sum, t) => sum + t.estDurationMin, 0);
  const donePct = prepTotalMin === 0 ? 0 : Math.round((prepDoneMin / prepTotalMin) * 100);

  const miscDoneCount = miscTasks.filter((t) => t.status === 'Done').length;

  const rankedCategories = rankCategories(categoryWeights);
  const ranked = rankedCategories.map(
    (category) => categoryWeights.find((w) => w.category === category)!
  );

  // rank is a unique 1-5 integer, so moving a category just swaps its rank
  // value with its neighbor's - a real total order, no ties to lose.
  async function move(index: number, otherIndex: number) {
    if (otherIndex < 0 || otherIndex >= ranked.length) return;
    const a = ranked[index];
    const b = ranked[otherIndex];
    const updated = categoryWeights.map((w) => {
      if (w.category === a.category) return { ...w, rank: b.rank };
      if (w.category === b.category) return { ...w, rank: a.rank };
      return w;
    });
    onCategoryWeightsChanged(await putCategoryWeights(updated));
  }

  async function handleApply() {
    if (!confirm('Re-prioritize every backlog task to match this ranking?')) return;
    setApplying(true);
    try {
      await applyCategoryWeights();
      onAppliedToBacklog();
    } finally {
      setApplying(false);
    }
  }

  const upcoming = [...interviews].sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt));
  const next = upcoming[0];

  return (
    <aside className="w-72 shrink-0 border-r border-zinc-200 dark:border-zinc-800 flex flex-col p-5 gap-5 overflow-y-auto">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-mono text-xs tracking-widest text-zinc-500 dark:text-zinc-500">INTERVIEW</p>
          <h1 className="text-2xl font-bold text-zinc-900 dark:text-white">Prep Tracker</h1>
        </div>
        <ThemeToggle />
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => onNavigateDay(-1)}
          className="w-8 h-8 flex items-center justify-center rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:border-zinc-300 dark:hover:border-zinc-700"
        >
          &lsaquo;
        </button>
        <span className="flex-1 text-center font-mono font-medium">{formatDayLabel(day)}</span>
        <button
          onClick={() => onNavigateDay(1)}
          className="w-8 h-8 flex items-center justify-center rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:border-zinc-300 dark:hover:border-zinc-700"
        >
          &rsaquo;
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
          <p className="text-xs text-zinc-500">Prep time</p>
          <p className="font-mono font-semibold text-lg">{formatDuration(prepTotalMin)}</p>
        </div>
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
          <p className="text-xs text-zinc-500">Done</p>
          <p className="font-mono font-semibold text-lg text-emerald-600 dark:text-emerald-400">{donePct}%</p>
        </div>
      </div>
      <div className="-mt-3 h-1 rounded-full bg-zinc-200 dark:bg-zinc-800 overflow-hidden">
        <div className="h-full bg-emerald-500 dark:bg-emerald-400" style={{ width: `${donePct}%` }} />
      </div>

      <div>
        <p className="font-mono text-xs tracking-widest text-zinc-500 mb-2">PRIORITIES</p>
        <div className="flex flex-col gap-1">
          {ranked.map((w, i) => {
            const meta = categoryMeta(w.category);
            const catTasks = prepTasks.filter((t) => t.category === w.category);
            const total = catTasks.reduce((s, t) => s + t.estDurationMin, 0);
            const done = catTasks
              .filter((t) => t.status === 'Done')
              .reduce((s, t) => s + t.estDurationMin, 0);
            return (
              <div key={w.category} className="flex items-center gap-2 py-1.5">
                <span className="text-zinc-400 dark:text-zinc-600 w-4 text-sm">{i + 1}</span>
                <span className={`w-2 h-2 rounded-full ${meta.dot}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate text-zinc-900 dark:text-zinc-100">{meta.short}</p>
                  <p className="font-mono text-xs text-zinc-500">
                    {formatDuration(done)}/{formatDuration(total)}
                  </p>
                </div>
                <div className="flex flex-col">
                  <button
                    onClick={() => move(i, i - 1)}
                    disabled={i === 0}
                    className="text-zinc-400 dark:text-zinc-600 hover:text-zinc-700 dark:hover:text-zinc-300 disabled:opacity-20 leading-none text-xs"
                  >
                    &#9650;
                  </button>
                  <button
                    onClick={() => move(i, i + 1)}
                    disabled={i === ranked.length - 1}
                    className="text-zinc-400 dark:text-zinc-600 hover:text-zinc-700 dark:hover:text-zinc-300 disabled:opacity-20 leading-none text-xs"
                  >
                    &#9660;
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        <button
          onClick={handleApply}
          disabled={applying}
          className="mt-2 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 dark:hover:text-indigo-300"
        >
          {applying ? 'Applying...' : 'Apply ranking to existing backlog'}
        </button>
      </div>

      <div className="border-t border-zinc-200 dark:border-zinc-800 pt-4">
        <p className="text-sm text-zinc-900 dark:text-zinc-100">Misc</p>
        <p className="font-mono text-xs text-zinc-500">
          {miscDoneCount}/{miscTasks.length} done
        </p>
      </div>

      {upcoming.length > 0 && (
        <div className="rounded-lg border border-amber-300 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/30 p-3">
          <p className="font-mono text-sm text-amber-700 dark:text-amber-300">{upcoming.length} interviews upcoming</p>
          {next && (
            <p className="font-mono text-xs text-amber-600/80 dark:text-amber-500/80">
              Next: {next.company ?? 'Unknown'} in {daysUntil(next.scheduledAt)}d
            </p>
          )}
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2">
        <button
          onClick={onGoToCalendar}
          className="text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 py-2 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:border-zinc-300 dark:hover:border-zinc-700"
        >
          Connect Google Calendar
        </button>
        <button
          type="button"
          onClick={() => void signOut()}
          className="text-sm rounded-lg py-2 text-zinc-400 dark:text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
