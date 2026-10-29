'use client';

import { useState } from 'react';
import { ProblemTag, createProblemTag, deleteProblemTag, updateProblemTag } from '../../lib/api';

interface Props {
  tags: ProblemTag[];
  onBack: () => void;
  onChanged: () => void;
}

const DEFAULT_COLOR = '#64748b';
const FIELD =
  'bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm';
const COLOR_INPUT =
  'w-9 h-9 shrink-0 cursor-pointer rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent p-1';

function TagRow({ tag, onChanged }: { tag: ProblemTag; onChanged: () => void }) {
  const [name, setName] = useState(tag.name);
  const [color, setColor] = useState(tag.color ?? DEFAULT_COLOR);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = name !== tag.name || color !== (tag.color ?? DEFAULT_COLOR);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await updateProblemTag(tag.id, { name, color });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save tag.');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    const used = `${tag.problemCount} problem${tag.problemCount === 1 ? '' : 's'}`;
    if (!confirm(`Delete tag "${tag.name}"? It will be removed from ${used}.`)) return;
    setBusy(true);
    await deleteProblemTag(tag.id);
    onChanged();
  }

  return (
    <div className="flex items-center gap-3 flex-wrap px-4 py-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40">
      <input
        type="color"
        value={color}
        onChange={(e) => setColor(e.target.value)}
        aria-label={`${tag.name} color`}
        className={COLOR_INPUT}
      />
      <input value={name} onChange={(e) => setName(e.target.value)} className={`${FIELD} w-56`} />
      <span className="font-mono text-xs text-zinc-500">
        {tag.problemCount} problem{tag.problemCount === 1 ? '' : 's'}
      </span>
      {error && <span className="text-xs text-rose-600 dark:text-rose-400">{error}</span>}
      <div className="ml-auto flex items-center gap-1">
        <button
          onClick={() => void save()}
          disabled={busy || !dirty || !name.trim()}
          className="px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700 disabled:opacity-40"
        >
          Save
        </button>
        <button
          onClick={() => void remove()}
          disabled={busy}
          title={`Delete ${tag.name}`}
          className="text-zinc-400 dark:text-zinc-600 hover:text-rose-500 dark:hover:text-rose-400 px-2"
        >
          &times;
        </button>
      </div>
    </div>
  );
}

export function TagManager({ tags, onBack, onChanged }: Props) {
  const [name, setName] = useState('');
  const [color, setColor] = useState(DEFAULT_COLOR);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createProblemTag({ name: name.trim(), color });
      setName('');
      setColor(DEFAULT_COLOR);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create tag.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
          &lsaquo; Back
        </button>
        <h2 className="text-lg font-semibold">Tags</h2>
      </div>

      <form onSubmit={create} className="flex items-center gap-3 flex-wrap">
        <input
          type="color"
          value={color}
          onChange={(e) => setColor(e.target.value)}
          aria-label="New tag color"
          className={COLOR_INPUT}
        />
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New tag, e.g. Backtracking"
          className={`${FIELD} flex-1 min-w-48`}
        />
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
        >
          + Tag
        </button>
      </form>
      {error && <p className="-mt-3 text-sm text-rose-600 dark:text-rose-400">{error}</p>}

      <div className="flex flex-col gap-2">
        {tags.length === 0 ? (
          <p className="text-sm text-zinc-500">No tags yet.</p>
        ) : (
          tags.map((tag) => (
            // Keyed on the saved values so a successful save re-seeds the row's inputs.
            <TagRow key={`${tag.id}:${tag.name}:${tag.color}`} tag={tag} onChanged={onChanged} />
          ))
        )}
      </div>
    </div>
  );
}
