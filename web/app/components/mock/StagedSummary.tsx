'use client';

import { EdgeOutcome, StagedRound, StagedStage } from '../../lib/api';
import { formatClock } from '../../lib/mock';
import { STAGE_STATUS_LABEL } from './StagePanel';
import { CARD, SECTION_TITLE } from './ui';

const STATUS_TEXT: Record<StagedStage['status'], string> = {
  passed: 'text-emerald-600 dark:text-emerald-400',
  skipped: 'text-amber-600 dark:text-amber-400',
  failed: 'text-rose-600 dark:text-rose-400',
  active: 'text-indigo-600 dark:text-indigo-400',
  locked: 'text-zinc-400 dark:text-zinc-500',
};

const EDGE: Record<EdgeOutcome, { mark: string; label: string; className: string }> = {
  hit: { mark: '✓', label: 'Handled up front', className: 'text-emerald-600 dark:text-emerald-400' },
  caught: { mark: '↻', label: 'Fixed after a failing run', className: 'text-amber-600 dark:text-amber-400' },
  missed: { mark: '✗', label: 'Missed', className: 'text-rose-600 dark:text-rose-400' },
  pending: { mark: '·', label: 'Not passing yet', className: 'text-zinc-500' },
  not_reached: { mark: '·', label: 'Not reached', className: 'text-zinc-400' },
};

// A finished staged round, stage by stage: pass/fail, time against the
// suggested pace, test runs, whether the stage extended or rewrote the
// previous stage's design, and which edge cases were handled.
export function StagedSummary({ staged }: { staged: StagedRound }) {
  const reached = staged.stages.filter((s) => s.status !== 'locked');
  const passed = staged.stages.filter((s) => s.status === 'passed').length;
  const edges = staged.stages.flatMap((s) => s.edgeCases);
  const upFront = edges.filter((e) => e.outcome === 'hit').length;
  const total = reached.reduce((sum, s) => sum + (s.timeSpentS ?? 0), 0);

  return (
    <section className="flex flex-col gap-3">
      <p className={`${SECTION_TITLE} mb-0`}>STAGES</p>
      <div className="grid grid-cols-3 gap-3">
        <Tile label="Stages passed" value={`${passed}`} of={`${staged.stages.length}`} />
        <Tile label="Edge cases up front" value={`${upFront}`} of={`${edges.length}`} />
        <Tile label="Time in stages" value={formatClock(total)} />
      </div>
      <ol className={`${CARD} divide-y divide-zinc-100 dark:divide-zinc-800/60`}>
        {staged.stages.map((stage) => (
          <StageResult key={stage.number} stage={stage} />
        ))}
      </ol>
    </section>
  );
}

function Tile({ label, value, of }: { label: string; value: string; of?: string }) {
  return (
    <div className={`${CARD} p-3`}>
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="font-mono font-semibold text-lg tabular-nums">
        {value}
        {of && <span className="text-xs text-zinc-400 dark:text-zinc-600"> / {of}</span>}
      </p>
    </div>
  );
}

function StageResult({ stage }: { stage: StagedStage }) {
  const locked = stage.status === 'locked';
  const over =
    stage.timeSpentS != null && stage.targetMin != null && stage.timeSpentS > stage.targetMin * 60;
  return (
    <li className="px-4 py-3 flex flex-col gap-2">
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="font-mono text-xs text-zinc-400 tabular-nums">{stage.number}</span>
        <span
          className={`flex-1 min-w-0 text-sm font-medium ${
            locked ? 'text-zinc-400 dark:text-zinc-500' : 'text-zinc-900 dark:text-zinc-100'
          }`}
        >
          {stage.title ?? `Stage ${stage.number}`}
        </span>
        <span className={`text-xs font-medium ${STATUS_TEXT[stage.status]}`}>
          {locked ? 'Not reached' : STAGE_STATUS_LABEL[stage.status]}
        </span>
      </div>

      {!locked && (
        <p className="pl-5 font-mono text-xs text-zinc-500 flex gap-x-4 gap-y-1 flex-wrap">
          {stage.timeSpentS != null && (
            <span className={over ? 'text-amber-600 dark:text-amber-400' : undefined}>
              {formatClock(stage.timeSpentS)}
              {stage.targetMin != null && ` of ${stage.targetMin} min`}
            </span>
          )}
          <span>
            {stage.runs} test run{stage.runs === 1 ? '' : 's'}
          </span>
          {stage.design && (
            <span
              className={
                stage.design.verdict === 'rewrote' ? 'text-amber-600 dark:text-amber-400' : undefined
              }
              title="How much of the previous stage's code is still there"
            >
              {stage.design.verdict === 'extended' ? 'Extended' : 'Rewrote'} stage {stage.number - 1}'s
              design ({Math.round(stage.design.kept * 100)}% kept)
            </span>
          )}
        </p>
      )}

      {stage.edgeCases.length > 0 && (
        <ul className="pl-5 flex flex-col gap-1">
          {stage.edgeCases.map((edge) => {
            const meta = EDGE[edge.outcome];
            return (
              <li key={edge.id} className="flex items-baseline gap-2 text-sm">
                <span className={`w-3 shrink-0 text-center font-mono ${meta.className}`} aria-hidden>
                  {meta.mark}
                </span>
                <span className="flex-1 min-w-0 text-zinc-700 dark:text-zinc-300">{edge.title}</span>
                <span className={`shrink-0 text-xs ${meta.className}`}>{meta.label}</span>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}
