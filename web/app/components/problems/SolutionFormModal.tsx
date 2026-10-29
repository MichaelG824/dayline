'use client';

import { useState } from 'react';
import { Solution, createSolution, updateSolution } from '../../lib/api';
import { DEFAULT_LANGUAGE, LANGUAGES } from '../../lib/problems';
import { CodeEditor } from './CodeEditor';
import { MarkdownField } from './Markdown';

interface Props {
  problemId: string;
  solution?: Solution;
  onClose: () => void;
  onSaved: () => void;
}

const FIELD =
  'bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm w-full';

export function SolutionFormModal({ problemId, solution, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(solution?.title ?? '');
  const [language, setLanguage] = useState(solution?.language ?? DEFAULT_LANGUAGE);
  const [code, setCode] = useState(solution?.code ?? '');
  const [timeComplexity, setTimeComplexity] = useState(solution?.timeComplexity ?? '');
  const [spaceComplexity, setSpaceComplexity] = useState(solution?.spaceComplexity ?? '');
  const [explanation, setExplanation] = useState(solution?.explanation ?? '');
  const [isOptimal, setIsOptimal] = useState(solution?.isOptimal ?? false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSubmitting(true);
    setError(null);
    const input = {
      title: title.trim(),
      language,
      code,
      timeComplexity: timeComplexity.trim() || null,
      spaceComplexity: spaceComplexity.trim() || null,
      explanation,
      isOptimal,
    };
    try {
      if (solution) {
        await updateSolution(solution.id, input);
      } else {
        await createSolution(problemId, input);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save solution.');
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold mb-1 text-zinc-900 dark:text-zinc-100">
          {solution ? 'Edit solution' : 'Add solution'}
        </h2>
        <p className="text-sm text-zinc-500 mb-4">One way of solving this problem: code, complexity, and why it works.</p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="grid gap-3 grid-cols-[1fr_11rem]">
            <input
              autoFocus
              placeholder="Approach, e.g. Hash map"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className={FIELD}
            />
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className={FIELD}>
              {LANGUAGES.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <CodeEditor value={code} onChange={setCode} language={language} />
          <div className="grid gap-3 grid-cols-2">
            <input
              placeholder="Time, e.g. O(n)"
              value={timeComplexity}
              onChange={(e) => setTimeComplexity(e.target.value)}
              className={`${FIELD} font-mono`}
            />
            <input
              placeholder="Space, e.g. O(n)"
              value={spaceComplexity}
              onChange={(e) => setSpaceComplexity(e.target.value)}
              className={`${FIELD} font-mono`}
            />
          </div>
          <MarkdownField
            value={explanation}
            onChange={setExplanation}
            placeholder="Why this works, edge cases..."
            rows={5}
          />
          <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={isOptimal}
              onChange={(e) => setIsOptimal(e.target.checked)}
              className="w-4 h-4 accent-indigo-500"
            />
            Optimal solution
          </label>
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
              disabled={submitting || !title.trim()}
              className="px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
            >
              {submitting ? 'Saving...' : solution ? 'Save changes' : 'Add solution'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
