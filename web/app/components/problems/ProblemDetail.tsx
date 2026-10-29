'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Problem,
  ProblemDetail as ProblemDetailData,
  ProblemTag,
  Solution,
  deleteProblem,
  deleteSolution,
  getProblem,
  updateProblem,
} from '../../lib/api';
import { formatDayLabel } from '../../lib/dates';
import { CONFIDENCE_LABELS, PROBLEM_STATUSES, STATUS_BADGE, formatShortDate, languageLabel, problemLabel } from '../../lib/problems';
import { formatDuration } from '../../lib/categories';
import { TaskFormModal } from '../TaskFormModal';
import { DifficultyBadge, TagChip } from './Badges';
import { CodeEditor } from './CodeEditor';
import { MarkdownView } from './Markdown';
import { SolutionFormModal } from './SolutionFormModal';
import { StarButton } from './StarButton';

interface Props {
  problemId: string;
  day: string;
  tags: ProblemTag[];
  onBack: () => void;
  onEdit: (problem: Problem) => void;
  onChanged: () => void;
  onDeleted: () => void;
  onTasksChanged: () => void;
}

const SECTION_TITLE = 'font-mono text-xs tracking-widest text-zinc-500 mb-2';
const CARD = 'rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40';

export function ProblemDetail({
  problemId,
  day,
  tags,
  onBack,
  onEdit,
  onChanged,
  onDeleted,
  onTasksChanged,
}: Props) {
  const [problem, setProblem] = useState<ProblemDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [solutionModal, setSolutionModal] = useState<{ solution?: Solution } | null>(null);
  const [scheduling, setScheduling] = useState(false);

  const load = useCallback(async () => {
    try {
      setProblem(await getProblem(problemId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load problem.');
    }
  }, [problemId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patch(input: Parameters<typeof updateProblem>[1]) {
    try {
      await updateProblem(problemId, input);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save problem.');
    }
  }

  async function handleDelete() {
    if (!problem) return;
    if (!confirm(`Delete "${problem.title}" and its ${problem.solutions.length} solution(s)?`)) return;
    await deleteProblem(problemId);
    onDeleted();
  }

  async function handleDeleteSolution(solution: Solution) {
    if (!confirm(`Delete solution "${solution.title}"?`)) return;
    await deleteSolution(solution.id);
    await load();
  }

  if (error && !problem) {
    return (
      <div className="flex flex-col gap-3 max-w-3xl">
        <button onClick={onBack} className="self-start text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
          &lsaquo; All problems
        </button>
        <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
      </div>
    );
  }
  if (!problem) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  const tagsById = new Map(tags.map((t) => [t.id, t]));
  const unusedTags = tags.filter((t) => !problem.tagIds.includes(t.id));

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <button onClick={onBack} className="self-start text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
        &lsaquo; All problems
      </button>

      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <StarButton starred={problem.starred} onToggle={() => void patch({ starred: !problem.starred })} />
            <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">
              {problem.number != null && <span className="text-zinc-400 dark:text-zinc-500">{problem.number}. </span>}
              {problem.title}
            </h2>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={problem.status}
              onChange={(e) => void patch({ status: e.target.value })}
              aria-label="Status"
              className={`text-xs font-mono px-2 py-1.5 rounded-lg border-0 ${STATUS_BADGE[problem.status] ?? ''}`}
            >
              {PROBLEM_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <button
              onClick={() => setScheduling(true)}
              className="px-3 py-1.5 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white"
            >
              Schedule practice
            </button>
            <button
              onClick={() => onEdit(problem)}
              className="px-3 py-1.5 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
            >
              Edit
            </button>
            <button
              onClick={() => void handleDelete()}
              className="px-3 py-1.5 text-sm rounded-lg text-zinc-500 hover:text-rose-600 dark:hover:text-rose-400"
            >
              Delete
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <DifficultyBadge difficulty={problem.difficulty} />
          {problem.confidence != null && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
              Confidence {CONFIDENCE_LABELS[problem.confidence] ?? problem.confidence}
            </span>
          )}
          {problem.url && (
            <a
              href={problem.url}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Open on LeetCode &#8599;
            </a>
          )}
        </div>

        <p className="font-mono text-xs text-zinc-500 flex gap-x-5 gap-y-1 flex-wrap">
          <span>Added {formatShortDate(problem.createdAt)}</span>
          {problem.lastAttemptedAt && <span>Last attempted {formatShortDate(problem.lastAttemptedAt)}</span>}
          {problem.solvedAt && <span>Solved {formatShortDate(problem.solvedAt)}</span>}
        </p>
        {error && <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      </div>

      <section>
        <p className={SECTION_TITLE}>TAGS</p>
        <div className="flex flex-wrap items-center gap-2">
          {problem.tagIds.map((id) => {
            const tag = tagsById.get(id);
            if (!tag) return null;
            return (
              <span key={id} className="inline-flex items-center gap-0.5">
                <TagChip name={tag.name} color={tag.color} />
                <button
                  onClick={() => void patch({ tagIds: problem.tagIds.filter((t) => t !== id) })}
                  title={`Remove ${tag.name}`}
                  className="text-zinc-400 dark:text-zinc-600 hover:text-rose-500 dark:hover:text-rose-400 px-1"
                >
                  &times;
                </button>
              </span>
            );
          })}
          {unusedTags.length > 0 && (
            <select
              value=""
              onChange={(e) => e.target.value && void patch({ tagIds: [...problem.tagIds, e.target.value] })}
              aria-label="Add tag"
              className="w-28 text-xs px-2 py-1 rounded-full border border-dashed border-zinc-300 dark:border-zinc-700 bg-transparent text-zinc-500"
            >
              <option value="">+ Add tag</option>
              {unusedTags.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </section>

      <section>
        <p className={SECTION_TITLE}>NOTES</p>
        <div className={`${CARD} p-4`}>
          <MarkdownView empty="No notes yet. Edit the problem to add some.">{problem.notes}</MarkdownView>
        </div>
      </section>

      <section>
        <p className={SECTION_TITLE}>PRACTICE SESSIONS</p>
        {problem.tasks.length === 0 ? (
          <p className="text-sm text-zinc-500">
            None yet. Schedule practice to put this problem on your plan.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {problem.tasks.map((t) => (
              <div
                key={t.id}
                className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 text-sm"
              >
                <span className={`flex-1 ${t.status === 'Done' ? 'line-through text-zinc-400 dark:text-zinc-500' : ''}`}>
                  {t.name}
                </span>
                <span className="font-mono text-xs text-zinc-500">
                  {t.plannedDate ? `${formatDayLabel(t.plannedDate)} · ` : t.recurs ? `${t.recurs} · ` : ''}
                  {formatDuration(t.estDurationMin)} · {t.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-2">
          <p className={`${SECTION_TITLE} mb-0`}>SOLUTIONS ({problem.solutions.length})</p>
          <button
            onClick={() => setSolutionModal({})}
            className="px-3 py-1.5 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
          >
            + Solution
          </button>
        </div>
        {problem.solutions.length === 0 ? (
          <p className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-700 p-6 text-center text-sm text-zinc-500">
            No solutions yet. A problem can hold many approaches - add your first.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {problem.solutions.map((s) => (
              <article
                key={s.id}
                className={`${CARD} p-4 flex flex-col gap-3 ${s.isOptimal ? 'border-emerald-300 dark:border-emerald-800' : ''}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-zinc-900 dark:text-zinc-100">{s.title}</h3>
                      {s.isOptimal && (
                        <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                          &#9733; Optimal
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-xs text-zinc-500 flex gap-3">
                      <span>{languageLabel(s.language)}</span>
                      {s.timeComplexity && <span>Time {s.timeComplexity}</span>}
                      {s.spaceComplexity && <span>Space {s.spaceComplexity}</span>}
                    </p>
                  </div>
                  <div className="flex items-center">
                    <button
                      onClick={() => setSolutionModal({ solution: s })}
                      title="Edit"
                      className="text-zinc-400 dark:text-zinc-600 hover:text-zinc-700 dark:hover:text-zinc-300 px-1"
                    >
                      &#9998;
                    </button>
                    <button
                      onClick={() => void handleDeleteSolution(s)}
                      title="Delete"
                      className="text-zinc-400 dark:text-zinc-600 hover:text-rose-500 dark:hover:text-rose-400 px-1"
                    >
                      &times;
                    </button>
                  </div>
                </div>
                {s.code.trim() && <CodeEditor value={s.code} language={s.language} readOnly />}
                {s.explanation.trim() && (
                  <div className="border-t border-zinc-200 dark:border-zinc-800 pt-3">
                    <MarkdownView>{s.explanation}</MarkdownView>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      {solutionModal && (
        <SolutionFormModal
          problemId={problemId}
          solution={solutionModal.solution}
          onClose={() => setSolutionModal(null)}
          onSaved={() => void load()}
        />
      )}

      {scheduling && (
        <TaskFormModal
          day={day}
          defaultCategory="Leetcode"
          defaultName={`Solve: ${problemLabel(problem)}`}
          problemId={problem.id}
          onClose={() => setScheduling(false)}
          onSaved={() => {
            void load();
            onTasksChanged();
          }}
        />
      )}
    </div>
  );
}
