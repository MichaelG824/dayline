'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  CriterionScore,
  MockEvent,
  MockSessionDetail,
  Proposal,
  confirmProposals,
  deleteMockSession,
  getMockSession,
  gradeMockSession,
} from '../../lib/api';
import { categoryMeta, formatDuration } from '../../lib/categories';
import { MAX_SCORE, SCORE_LABELS, formatClock, packLabel, scoreFill, scoreText } from '../../lib/mock';
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
import { TestResults } from './TestResults';

interface Props {
  sessionId: string;
  day: string;
  onBack: () => void;
  onOpenWorkspace: () => void;
  onOpenQuestion: (questionId: string) => void;
  onDeleted: () => void;
  onTasksChanged: () => void;
}

export function SessionView({
  sessionId,
  day,
  onBack,
  onOpenWorkspace,
  onOpenQuestion,
  onDeleted,
  onTasksChanged,
}: Props) {
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
        <BackButton onClick={onBack}>Practice</BackButton>
        <ErrorText>{error}</ErrorText>
      </div>
    );
  }
  if (!session) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  const card = session.scorecard;
  const isLive = session.kind === 'live';
  const inProgress = isLive && session.status === 'live';
  // Where graded evidence has to come from, for the "not found" labels.
  const evidenceSource = isLive ? 'session' : 'transcript';
  const length =
    session.startedAt && session.endedAt
      ? (Date.parse(session.endedAt) - Date.parse(session.startedAt)) / 1000
      : null;
  const addedNames = new Set(session.tasks.map((t) => t.name));
  const unverified = card ? card.criteria.flatMap((c) => c.evidence).filter((e) => !e.verified).length : 0;

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <BackButton onClick={onBack}>Practice</BackButton>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">{session.title}</h2>
          <p className="font-mono text-xs text-zinc-500 flex gap-x-5 gap-y-1 flex-wrap mt-1">
            <span>{formatShortDate(session.createdAt)}</span>
            {isLive && <span>Live session{session.pack ? ` · ${packLabel(session.pack)}` : ''}</span>}
            {length != null && <span>{formatClock(length)} long</span>}
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
          {inProgress ? (
            <button onClick={onOpenWorkspace} className={PRIMARY_BUTTON}>
              Open workspace
            </button>
          ) : (
            <button
              onClick={() => void handleGrade()}
              disabled={grading || !session.rubricId}
              title={session.rubricId ? undefined : 'This session has no rubric'}
              className={card ? SECONDARY_BUTTON : PRIMARY_BUTTON}
            >
              {grading ? 'Grading…' : card ? 'Re-grade' : 'Grade'}
            </button>
          )}
          <button onClick={() => void handleDelete()} className={DANGER_BUTTON}>
            Delete
          </button>
        </div>
      </div>

      {error && <ErrorText>{error}</ErrorText>}

      {inProgress ? (
        <div className={`${CARD} px-4 py-8 text-center text-sm text-zinc-500`}>
          This session is still in progress. End it from the workspace to grade it.
        </div>
      ) : !card ? (
        <div className={`${CARD} px-4 py-8 text-center text-sm text-zinc-500`}>
          {grading
            ? `Reading the whole ${isLive ? 'session' : 'transcript'}. Usually under a minute.`
            : session.rubricId
              ? 'Not graded yet. Grade it to get a scorecard.'
              : 'Not graded yet. This session has no rubric to grade against.'}
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
              <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
                <GraderText text={card.summary} />
              </p>
              {card.strengths.length > 0 && (
                <ul className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
                  {card.strengths.map((s, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-emerald-600 dark:text-emerald-400">+</span>
                      <span>
                        <GraderText text={s} />
                      </span>
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
                  {unverified} quote{unverified === 1 ? '' : 's'} not found in the {evidenceSource}
                </p>
              )}
            </div>
            {card.criteria.map((c) => (
              <CriterionCard key={c.key} criterion={c} source={evidenceSource} />
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
                        {area?.why && (
                          <span className="block text-sm text-zinc-500">
                            <GraderText text={area.why} />
                          </span>
                        )}
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

      {isLive && !inProgress && <WorkRecord session={session} />}

      {session.transcript.trim() && (
        <details className="group">
          <summary className={`${SECTION_TITLE} cursor-pointer select-none list-none`}>
            <span className="group-open:hidden">&rsaquo;</span>
            <span className="hidden group-open:inline">&#8964;</span> TRANSCRIPT
          </summary>
          <pre className={`${CARD} p-4 text-xs whitespace-pre-wrap font-mono text-zinc-600 dark:text-zinc-400`}>
            {session.transcript}
          </pre>
        </details>
      )}
    </div>
  );
}

// One timeline line: an event, or a run of saves to the same file.
interface TimelineEntry {
  event: MockEvent;
  lastAt: string | null;
  saves: number;
}

function eventText({ event, saves }: TimelineEntry): string {
  const d = event.data;
  switch (event.kind) {
    case 'session_started':
      return 'Started';
    case 'file_saved':
      return `Saved ${d.path} (+${d.added ?? 0} −${d.removed ?? 0}${saves > 1 ? `, ${saves} saves` : ''})`;
    case 'tests_run':
      return `Ran tests: ${d.passed ?? 0} passed, ${Number(d.failed ?? 0) + Number(d.errors ?? 0)} failing`;
    case 'command_run':
      return `$ ${d.command}${d.exitCode ? `  (exit ${d.exitCode})` : ''}`;
    case 'session_ended':
      return d.sandboxLost ? 'Ended (the sandbox had already been deleted)' : 'Ended';
  }
}

// Back-to-back saves of one file read as one line with its time span, like
// the grader sees them (mock/worklog.py).
function timelineEntries(events: MockEvent[]): TimelineEntry[] {
  const out: TimelineEntry[] = [];
  for (const event of events) {
    const last = out[out.length - 1];
    if (last && last.event.kind === 'file_saved' && event.kind === 'file_saved' && last.event.data.path === event.data.path) {
      last.event = {
        ...last.event,
        data: {
          ...last.event.data,
          added: Number(last.event.data.added ?? 0) + Number(event.data.added ?? 0),
          removed: Number(last.event.data.removed ?? 0) + Number(event.data.removed ?? 0),
        },
      };
      last.lastAt = event.at;
      last.saves += 1;
    } else {
      out.push({ event, lastAt: event.at, saves: 1 });
    }
  }
  return out;
}

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-zinc-500 font-semibold';
  if (line.startsWith('@@')) return 'text-indigo-600 dark:text-indigo-400';
  if (line.startsWith('+')) return 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-800 dark:text-emerald-300';
  if (line.startsWith('-')) return 'bg-rose-50 dark:bg-rose-500/10 text-rose-800 dark:text-rose-300';
  return 'text-zinc-600 dark:text-zinc-400';
}

// What a live session left behind: the last test run, the timeline, and the diff.
function WorkRecord({ session }: { session: MockSessionDetail }) {
  const start = session.startedAt ? Date.parse(session.startedAt) : null;
  const entries = timelineEntries(session.events ?? []);
  const clock = (at: string | null) => (start && at ? formatClock((Date.parse(at) - start) / 1000) : '');
  const diff = session.finalDiff ?? '';
  return (
    <>
      <section>
        <p className={SECTION_TITLE}>LAST TEST RUN</p>
        <div className={CARD}>
          <TestResults
            report={session.testReport ?? null}
            running={false}
            empty="The Run tests button was never used. Test runs in the terminal are in the timeline."
          />
        </div>
      </section>

      <section>
        <p className={SECTION_TITLE}>TIMELINE</p>
        <ol className={`${CARD} px-4 py-3 grid grid-cols-[auto_1fr] gap-x-5 gap-y-1`}>
          {entries.map((entry, i) => (
            <li key={i} className="contents text-sm">
              <span className="font-mono text-xs leading-5 text-zinc-400 tabular-nums whitespace-nowrap">
                {clock(entry.event.at)}
                {entry.saves > 1 && `–${clock(entry.lastAt)}`}
              </span>
              <span
                className={`min-w-0 break-words text-zinc-700 dark:text-zinc-300 ${
                  entry.event.kind === 'command_run' ? 'font-mono text-xs leading-5' : ''
                }`}
              >
                {eventText(entry)}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <p className={SECTION_TITLE}>YOUR CHANGES</p>
        {diff.trim() ? (
          <div className={`${CARD} overflow-x-auto`}>
            <pre className="py-2 text-xs font-mono">
              {diff.replace(/\n$/, '').split('\n').map((line, i) => (
                <div key={i} className={`px-4 whitespace-pre ${diffLineClass(line)}`}>
                  {line || ' '}
                </div>
              ))}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-zinc-500">No changes to the starting repo.</p>
        )}
      </section>
    </>
  );
}

// The grader writes plain text but marks code with `backticks`.
function GraderText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`\n]+`)/).map((part, i) =>
        part.length > 2 && part.startsWith('`') && part.endsWith('`') ? (
          <code key={i} className="rounded bg-zinc-100 dark:bg-zinc-800/80 px-1 py-px font-mono text-[0.85em]">
            {part.slice(1, -1)}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

// Weak-area proposals not yet turned into tasks. Tasks link back to the
// session, so a proposal counts as added when a linked task has its name.
function pendingProposals(session: MockSessionDetail): Proposal[] {
  const added = new Set(session.tasks.map((t) => t.name));
  return session.proposals.filter((p) => !added.has(String(p.name)));
}

function CriterionCard({ criterion, source }: { criterion: CriterionScore; source: string }) {
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
                <span className="ml-2 font-mono text-xs text-amber-600 dark:text-amber-400">not in {source}</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-zinc-500">No evidence in the {source}.</p>
      )}
      {criterion.improvement && (
        <p className="text-sm text-zinc-800 dark:text-zinc-200">
          <span className="font-mono text-xs text-indigo-600 dark:text-indigo-400">NEXT TIME </span>
          <GraderText text={criterion.improvement} />
        </p>
      )}
    </div>
  );
}
