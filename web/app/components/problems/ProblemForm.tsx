'use client';

import { useState } from 'react';
import { Problem, ProblemInput, ProblemTag, createProblem, updateProblem } from '../../lib/api';
import { CONFIDENCE_LABELS, DIFFICULTIES, PROBLEM_STATUSES } from '../../lib/problems';
import { TagChip } from './Badges';
import { MarkdownField } from './Markdown';

interface Props {
  tags: ProblemTag[];
  problem?: Problem;
  onSaved: (problem: Problem) => void;
  onCancel: () => void;
}

const FIELD =
  'bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm w-full';

function Label({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-xs font-mono text-zinc-500 mb-1">
      {children}
    </label>
  );
}

export function ProblemForm({ tags, problem, onSaved, onCancel }: Props) {
  const [number, setNumber] = useState(problem?.number != null ? String(problem.number) : '');
  const [title, setTitle] = useState(problem?.title ?? '');
  const [slug, setSlug] = useState(problem?.slug ?? '');
  const [url, setUrl] = useState(problem?.url ?? '');
  const [difficulty, setDifficulty] = useState(problem?.difficulty ?? 'Medium');
  const [status, setStatus] = useState(problem?.status ?? 'To do');
  const [confidence, setConfidence] = useState(problem?.confidence ?? 0);
  const [notes, setNotes] = useState(problem?.notes ?? '');
  const [starred, setStarred] = useState(problem?.starred ?? false);
  const [tagIds, setTagIds] = useState<string[]>(problem?.tagIds ?? []);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleTag(id: string) {
    setTagIds((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setError('Title is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const input: ProblemInput = {
      number: number ? Number(number) : null,
      title: title.trim(),
      slug: slug.trim() || null,
      url: url.trim() || null,
      difficulty,
      status,
      confidence: confidence || null,
      notes,
      starred,
      tagIds,
    };
    try {
      onSaved(problem ? await updateProblem(problem.id, input) : await createProblem(input));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save problem.');
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
        >
          &lsaquo; Back
        </button>
        <h2 className="text-lg font-semibold">{problem ? 'Edit problem' : 'Add problem'}</h2>
      </div>

      <div className="grid gap-3 grid-cols-[7rem_1fr]">
        <div>
          <Label htmlFor="problem-number">LC #</Label>
          <input
            id="problem-number"
            type="number"
            min={1}
            inputMode="numeric"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="1"
            className={FIELD}
          />
        </div>
        <div>
          <Label htmlFor="problem-title">Title</Label>
          <input
            id="problem-title"
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Two Sum"
            className={FIELD}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="problem-slug">Slug</Label>
          <input
            id="problem-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="two-sum"
            className={FIELD}
          />
        </div>
        <div>
          <Label htmlFor="problem-url">URL</Label>
          <input
            id="problem-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://leetcode.com/problems/two-sum/"
            className={FIELD}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label htmlFor="problem-difficulty">Difficulty</Label>
          <select
            id="problem-difficulty"
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
            className={FIELD}
          >
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="problem-status">Status</Label>
          <select id="problem-status" value={status} onChange={(e) => setStatus(e.target.value)} className={FIELD}>
            {PROBLEM_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="problem-confidence">Confidence</Label>
          <select
            id="problem-confidence"
            value={confidence}
            onChange={(e) => setConfidence(Number(e.target.value))}
            className={FIELD}
          >
            <option value={0}>Not set</option>
            {Object.entries(CONFIDENCE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <Label>Notes</Label>
        <MarkdownField value={notes} onChange={setNotes} placeholder="Approach, gotchas, patterns..." rows={10} />
      </div>

      <div>
        <Label>Tags</Label>
        {tags.length === 0 ? (
          <p className="text-sm text-zinc-500">No tags yet. Create some under Manage tags.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => {
              const selected = tagIds.includes(tag.id);
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggleTag(tag.id)}
                  aria-pressed={selected}
                  className={`rounded-full transition-opacity ${selected ? 'opacity-100' : 'opacity-40 hover:opacity-75'}`}
                >
                  <TagChip name={tag.name} color={tag.color} />
                </button>
              );
            })}
          </div>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
        <input
          type="checkbox"
          checked={starred}
          onChange={(e) => setStarred(e.target.checked)}
          className="w-4 h-4 accent-indigo-500"
        />
        Starred
      </label>

      {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || !title.trim()}
          className="px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
        >
          {submitting ? 'Saving...' : problem ? 'Save changes' : 'Add problem'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-sm text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
