'use client';

import { useEffect, useState } from 'react';
import { MockSessionSummary, getMockSessions } from '../../lib/api';
import { MAX_SCORE, scoreText } from '../../lib/mock';
import { formatShortDate } from '../../lib/problems';
import { CARD, ErrorText, Pill, PRIMARY_BUTTON, SECONDARY_BUTTON } from './ui';

interface Props {
  onOpen: (session: MockSessionSummary) => void;
  onNewLive: () => void;
  onNewGrading: () => void;
}

export function SessionList({ onOpen, onNewLive, onNewGrading }: Props) {
  const [sessions, setSessions] = useState<MockSessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMockSessions()
      .then(setSessions)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load sessions.'));
  }, []);

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!sessions) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  const graded = sessions.filter((s) => s.overallScore != null);
  const average =
    graded.length > 0 ? graded.reduce((sum, s) => sum + (s.overallScore ?? 0), 0) / graded.length : null;

  return (
    <div className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold">Practice</h2>
          <p className="text-sm text-zinc-500">
            Code a staged round or a practice repo in a sandbox, or paste a past mock's transcript. Either way
            you get scored against your rubric, with evidence.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onNewGrading} className={SECONDARY_BUTTON}>
            Grade a transcript
          </button>
          <button onClick={onNewLive} className={PRIMARY_BUTTON}>
            Start a live session
          </button>
        </div>
      </div>

      {average != null && (
        <div className="grid grid-cols-2 gap-3 max-w-sm">
          <div className={`${CARD} p-3`}>
            <p className="text-xs text-zinc-500">Graded sessions</p>
            <p className="font-mono font-semibold text-lg">{graded.length}</p>
          </div>
          <div className={`${CARD} p-3`}>
            <p className="text-xs text-zinc-500">Average score</p>
            <p className={`font-mono font-semibold text-lg ${scoreText(average)}`}>
              {average.toFixed(2)}
              <span className="text-xs text-zinc-400 dark:text-zinc-600"> / {MAX_SCORE}</span>
            </p>
          </div>
        </div>
      )}

      {sessions.length === 0 ? (
        <div className={`${CARD} px-4 py-10 text-center text-sm text-zinc-500`}>
          No sessions yet. Start a live session, or grade the transcript of a past mock to see where you
          stand.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => onOpen(s)}
              className={`${CARD} flex items-center gap-3 px-4 py-3 text-left hover:border-zinc-300 dark:hover:border-zinc-700`}
            >
              <span className="flex-1 min-w-0 truncate text-sm font-medium">{s.title}</span>
              {s.kind === 'live' &&
                (s.status === 'live' ? (
                  <Pill className="!bg-emerald-100 dark:!bg-emerald-500/15 !text-emerald-700 dark:!text-emerald-300">
                    In progress
                  </Pill>
                ) : s.stagedProblemId ? (
                  <Pill title="Stages passed">
                    Staged · {s.stagesPassed}/{s.stageCount}
                  </Pill>
                ) : (
                  <Pill>Live</Pill>
                ))}
              <span className="font-mono text-xs text-zinc-500">{formatShortDate(s.createdAt)}</span>
              <span
                className={`w-20 text-right font-mono text-sm tabular-nums ${
                  s.overallScore != null ? scoreText(s.overallScore) : 'text-zinc-400 dark:text-zinc-600'
                }`}
              >
                {s.overallScore != null ? s.overallScore.toFixed(2) : 'ungraded'}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
