'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  CriterionScore,
  MockSessionDetail,
  Proposal,
  confirmProposals,
  deleteMockSession,
  getMockSession,
  gradeMockSession,
} from '../../lib/api';
import { categoryMeta, formatDuration } from '../../lib/categories';
import { MAX_SCORE, SCORE_LABELS, scoreFill, scoreText } from '../../lib/mock';
import { formatShortDate } from '../../lib/problems';
import {
  BackButton,
  CARD,
  DANGER_BUTTON,
  ErrorText,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  SECTION_TITLE,
} from './ui';

interface Props {
  sessionId: string;
  day: string;
  onBack: () => void;
  onOpenQuestion: (questionId: string) => void;
  onDeleted: () => void;
  onTasksChanged: () => void;
}

export function SessionView({ sessionId, day, onBack, onOpenQuestion, onDeleted, onTasksChanged }: Props) {
  const [session, setSession] = useState<MockSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [grading, setGrading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);

  // A fresh scorecard starts with every not-yet-added weak area selected; a
  // reload (after adding some) keeps whatever the user chose for the rest.
  const load = useCallback(
    async (resetSelection: boolean) => {
      try {
        const next = await getMockSession(sessionId);
        setSession(next);
        setSelected((prev) => {
          const open = pendingProposals(next).map((p) => p.id);
          return new Set(resetSelection ? open : open.filter((id) => prev.has(id)));
        });
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not load session.');
      }
    },
    [sessionId]
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  async function handleGrade() {
    setGrading(true);
    setError(null);
    try {
      const next = await gradeMockSession(sessionId);
      setSession(next);
      setSelected(new Set(pendingProposals(next).map((p) => p.id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Grading failed.');
    } finally {
      setGrading(false);
    }
  }

  async function handleDelete() {
    if (!session || !confirm(`Delete "${session.title}" and its scorecard?`)) return;
    await deleteMockSession(session.id);
    onDeleted();
  }

  async function handleAddTasks() {
    if (!session) return;
    // Only what is still open is on offer, so already-added tasks are never
    // logged as rejected when the rest are added later.
    const offered = pendingProposals(session);
    const chosen = offered.filter((p) => selected.has(p.id));
    setAdding(true);
    setError(null);
    try {
      // The same confirm path as chat proposals: tasks are only ever created here.
      await confirmProposals(day, chosen, offered);
      onTasksChanged();
      await load(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add tasks.');
    } finally {
      setAdding(false);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (error && !session) {
    return (
      <div className="flex flex-col gap-3 max-w-3xl">
        <BackButton onClick={onBack}>Grading</BackButton>
        <ErrorText>{error}</ErrorText>
      </div>
    );
  }
  if (!session) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  const card = session.scorecard;
  const addedNames = new Set(session.tasks.map((t) => t.name));
  const unverified = card ? card.criteria.flatMap((c) => c.evidence).filter((e) => !e.verified).length : 0;

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <BackButton onClick={onBack}>Grading</BackButton>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">{session.title}</h2>
          <p className="font-mono text-xs text-zinc-500 flex gap-x-5 gap-y-1 flex-wrap mt-1">
            <span>{formatShortDate(session.createdAt)}</span>
            {card && <span>Graded by {card.graderModel}</span>}
            {session.questionId && (
              <button
                onClick={() => onOpenQuestion(session.questionId!)}
                className="text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                Open question
              </button>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void handleGrade()}
            disabled={grading || !session.rubricId}
            title={session.rubricId ? undefined : 'This session has no rubric'}
            className={card ? SECONDARY_BUTTON : PRIMARY_BUTTON}
          >
            {grading ? 'Grading…' : card ? 'Re-grade' : 'Grade'}
          </button>
          <button onClick={() => void handleDelete()} className={DANGER_BUTTON}>
            Delete
          </button>
        </div>
      </div>

      {error && <ErrorText>{error}</ErrorText>}

      {!card ? (
        <div className={`${CARD} px-4 py-8 text-center text-sm text-zinc-500`}>
          {grading
            ? 'Reading the whole transcript. Usually under a minute.'
            : 'Not graded yet. Grade it to get a scorecard.'}
        </div>
      ) : (
        <>
          <section className={`${CARD} p-5 flex flex-col sm:flex-row gap-5`}>
            <div className="shrink-0 text-center sm:text-left">
              <p className="text-xs text-zinc-500">Overall</p>
              <p className={`font-mono text-4xl font-semibold tabular-nums ${scoreText(card.overallScore)}`}>
                {card.overallScore.toFixed(2)}
              </p>
              <p className="font-mono text-xs text-zinc-400 dark:text-zinc-600">out of {MAX_SCORE}</p>
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-3">
              <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">{card.summary}</p>
              {card.strengths.length > 0 && (
                <ul className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
                  {card.strengths.map((s, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-emerald-600 dark:text-emerald-400">+</span>
                      {s}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between gap-2 flex-wrap">
              <p className={`${SECTION_TITLE} mb-0`}>BY CRITERION</p>
              {unverified > 0 && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  {unverified} quote{unverified === 1 ? '' : 's'} not found in the transcript
                </p>
              )}
            </div>
            {card.criteria.map((c) => (
              <CriterionCard key={c.key} criterion={c} />
            ))}
          </section>

          {session.proposals.length > 0 && (
            <section className="flex flex-col gap-3">
              <p className={`${SECTION_TITLE} mb-0`}>PRACTISE NEXT</p>
              <div className={`${CARD} divide-y divide-zinc-100 dark:divide-zinc-800/60`}>
                {session.proposals.map((p, i) => {
                  const area = card.weakAreas[i];
                  const added = addedNames.has(String(p.name));
                  const meta = categoryMeta(String(p.category));
                  return (
                    <label
                      key={p.id}
                      className={`flex items-start gap-3 px-4 py-3 ${added ? 'opacity-60' : 'cursor-pointer'}`}
                    >
                      <input
                        type="checkbox"
                        checked={added || selected.has(p.id)}
                        disabled={added}
                        onChange={() => toggle(p.id)}
                        className="mt-1 accent-indigo-500"
                      />
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                          {String(p.name)}
                        </span>
                        {area?.why && <span className="block text-sm text-zinc-500">{area.why}</span>}
                        <span className="mt-1 flex items-center gap-3 font-mono text-xs">
                          <span className={`flex items-center gap-1.5 ${meta.text}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                            {meta.short}
                          </span>
                          <span className="text-zinc-500">{formatDuration(Number(p.est_duration_min))}</span>
                          {added && <span className="text-emerald-600 dark:text-emerald-400">Added to tasks</span>}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
              <button
                onClick={() => void handleAddTasks()}
                disabled={adding || !pendingProposals(session).some((p) => selected.has(p.id))}
                className={`self-start ${PRIMARY_BUTTON}`}
              >
                {adding ? 'Adding…' : 'Add selected as prep tasks'}
              </button>
            </section>
          )}
        </>
      )}

      <details className="group">
        <summary className={`${SECTION_TITLE} cursor-pointer select-none list-none`}>
          <span className="group-open:hidden">&rsaquo;</span>
          <span className="hidden group-open:inline">&#8964;</span> TRANSCRIPT
        </summary>
        <pre className={`${CARD} p-4 text-xs whitespace-pre-wrap font-mono text-zinc-600 dark:text-zinc-400`}>
          {session.transcript}
        </pre>
      </details>
    </div>
  );
}

// Weak-area proposals not yet turned into tasks. Tasks link back to the
// session, so a proposal counts as added when a linked task has its name.
function pendingProposals(session: MockSessionDetail): Proposal[] {
  const added = new Set(session.tasks.map((t) => t.name));
  return session.proposals.filter((p) => !added.has(String(p.name)));
}

function CriterionCard({ criterion }: { criterion: CriterionScore }) {
  return (
    <div className={`${CARD} p-4 flex flex-col gap-3`}>
      <div className="flex items-center gap-3 flex-wrap">
        <p className="flex-1 min-w-0 text-sm font-medium text-zinc-900 dark:text-zinc-100">{criterion.title}</p>
        <div className="flex items-center gap-2">
          <div className="flex gap-1" aria-hidden>
            {Array.from({ length: MAX_SCORE }, (_, i) => (
              <span
                key={i}
                className={`h-1.5 w-5 rounded-full ${
                  i < criterion.score ? scoreFill(criterion.score) : 'bg-zinc-200 dark:bg-zinc-800'
                }`}
              />
            ))}
          </div>
          <span className={`font-mono text-xs tabular-nums ${scoreText(criterion.score)}`}>
            {criterion.score}/{MAX_SCORE} · {SCORE_LABELS[criterion.score]}
          </span>
        </div>
      </div>
      {criterion.evidence.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {criterion.evidence.map((e, i) => (
            <li
              key={i}
              className={`border-l-2 pl-3 text-sm ${
                e.verified
                  ? 'border-zinc-300 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400'
                  : 'border-amber-400 text-zinc-500'
              }`}
            >
              &ldquo;{e.quote}&rdquo;
              {!e.verified && (
                <span className="ml-2 font-mono text-xs text-amber-600 dark:text-amber-400">not in transcript</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-zinc-500">No evidence in the transcript.</p>
      )}
      {criterion.improvement && (
        <p className="text-sm text-zinc-800 dark:text-zinc-200">
          <span className="font-mono text-xs text-indigo-600 dark:text-indigo-400">NEXT TIME </span>
          {criterion.improvement}
        </p>
      )}
    </div>
  );
}
