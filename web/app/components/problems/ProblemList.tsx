'use client';

import { useMemo, useState } from 'react';
import { Problem, ProblemTag } from '../../lib/api';
import { DIFFICULTIES, PROBLEM_STATUSES, isDueForReview, problemLabel } from '../../lib/problems';
import { DifficultyBadge, StatusBadge, TagChip } from './Badges';
import { StarButton } from './StarButton';

interface Props {
  problems: Problem[];
  tags: ProblemTag[];
  onOpen: (problemId: string) => void;
  onNew: () => void;
  onManageTags: () => void;
  onToggleStar: (problem: Problem) => void;
  onExport: () => void;
}

const SELECT =
  'bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm';

function Stat({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className={`font-mono font-semibold text-lg ${accent ?? ''}`}>{value}</p>
    </div>
  );
}

export function ProblemList({
  problems,
  tags,
  onOpen,
  onNew,
  onManageTags,
  onToggleStar,
  onExport,
}: Props) {
  const [query, setQuery] = useState('');
  const [tagId, setTagId] = useState('');
  const [difficulty, setDifficulty] = useState('');
  const [status, setStatus] = useState('');

  const tagsById = useMemo(() => new Map(tags.map((t) => [t.id, t])), [tags]);
  const due = problems.filter((p) => isDueForReview(p));

  const q = query.trim().toLowerCase();
  const filtered = problems.filter(
    (p) =>
      (!q || p.title.toLowerCase().includes(q) || String(p.number ?? '') === q) &&
      (!tagId || p.tagIds.includes(tagId)) &&
      (!difficulty || p.difficulty === difficulty) &&
      (!status || p.status === status)
  );
  const hasFilters = !!(q || tagId || difficulty || status);

  function clearFilters() {
    setQuery('');
    setTagId('');
    setDifficulty('');
    setStatus('');
  }

  return (
    <div className="flex flex-col gap-6 max-w-5xl">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-lg font-semibold">LeetCode Problems</h2>
        <div className="flex gap-2">
          <button
            onClick={onExport}
            className="px-4 py-2 text-sm rounded-lg text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
          >
            Export JSON
          </button>
          <button
            onClick={onManageTags}
            className="px-4 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
          >
            Manage tags
          </button>
          <button
            onClick={onNew}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white"
          >
            + Problem
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Total" value={problems.length} />
        <Stat
          label="Solved"
          value={problems.filter((p) => p.status === 'Solved').length}
          accent="text-emerald-600 dark:text-emerald-400"
        />
        <Stat label="Due for review" value={due.length} accent="text-violet-600 dark:text-violet-400" />
        <Stat label="Starred" value={problems.filter((p) => p.starred).length} accent="text-amber-600 dark:text-amber-400" />
      </div>

      {due.length > 0 && (
        <section>
          <h3 className="font-mono text-sm mb-2 text-violet-600 dark:text-violet-400">
            <span className="text-zinc-400 dark:text-zinc-600">&bull;</span> DUE FOR REVIEW
          </h3>
          <div className="flex flex-col gap-2">
            {due.map((p) => (
              <button
                key={p.id}
                onClick={() => onOpen(p.id)}
                className="flex items-center gap-3 px-4 py-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 hover:border-zinc-300 dark:hover:border-zinc-700 text-left"
              >
                <span className="flex-1 truncate text-zinc-900 dark:text-zinc-100">{problemLabel(p)}</span>
                <DifficultyBadge difficulty={p.difficulty} />
                <StatusBadge status={p.status} />
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title or number..."
            className={`${SELECT} flex-1 min-w-48`}
          />
          <select value={tagId} onChange={(e) => setTagId(e.target.value)} className={SELECT}>
            <option value="">All tags</option>
            {tags.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className={SELECT}>
            <option value="">All difficulties</option>
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={SELECT}>
            <option value="">All statuses</option>
            {PROBLEM_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {hasFilters && (
            <button
              onClick={clearFilters}
              className="px-3 py-2 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
            >
              Clear
            </button>
          )}
        </div>

        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-zinc-800 text-left text-xs font-mono text-zinc-500">
                <th className="w-10 px-3 py-2" />
                <th className="w-16 px-3 py-2 font-normal">#</th>
                <th className="px-3 py-2 font-normal">Title</th>
                <th className="w-24 px-3 py-2 font-normal">Difficulty</th>
                <th className="w-28 px-3 py-2 font-normal">Status</th>
                <th className="px-3 py-2 font-normal">Tags</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-10 text-center text-zinc-500">
                    {problems.length === 0
                      ? 'No problems yet. Add one to get started.'
                      : 'No problems match these filters.'}
                  </td>
                </tr>
              ) : (
                filtered.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => onOpen(p.id)}
                    className="border-b last:border-b-0 border-zinc-100 dark:border-zinc-800/60 hover:bg-zinc-50 dark:hover:bg-zinc-800/30 cursor-pointer"
                  >
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <StarButton starred={p.starred} onToggle={() => onToggleStar(p)} />
                    </td>
                    <td className="px-3 py-2 font-mono text-zinc-500">{p.number ?? '-'}</td>
                    <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">{p.title}</td>
                    <td className="px-3 py-2">
                      <DifficultyBadge difficulty={p.difficulty} />
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {p.tagIds.map((id) => {
                          const tag = tagsById.get(id);
                          return tag ? <TagChip key={id} name={tag.name} color={tag.color} /> : null;
                        })}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
