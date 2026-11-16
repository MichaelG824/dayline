'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ReplayEntry, ReplayGroup, SessionReplay as Replay, getSessionReplay } from '../../lib/api';
import { formatClock } from '../../lib/mock';
import { DiffView } from './DiffView';
import { CARD, ErrorText, SECTION_TITLE } from './ui';

const GROUPS: { id: ReplayGroup; label: string; dot: string; chip: string }[] = [
  {
    id: 'edits',
    label: 'Edits',
    dot: 'bg-sky-500',
    chip: 'border-sky-300 dark:border-sky-500/40 text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-500/10',
  },
  {
    id: 'tests',
    label: 'Tests',
    dot: 'bg-emerald-500',
    chip: 'border-emerald-300 dark:border-emerald-500/40 text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-500/10',
  },
  {
    id: 'app',
    label: 'App',
    dot: 'bg-violet-500',
    chip: 'border-violet-300 dark:border-violet-500/40 text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-500/10',
  },
  {
    id: 'assistant',
    label: 'AI assistant',
    dot: 'bg-indigo-500',
    chip: 'border-indigo-300 dark:border-indigo-500/40 text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-500/10',
  },
  {
    id: 'chat',
    label: 'Interviewer',
    dot: 'bg-zinc-400 dark:bg-zinc-500',
    chip: 'border-zinc-300 dark:border-zinc-600 text-zinc-700 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-800',
  },
  {
    id: 'stages',
    label: 'Stages',
    dot: 'bg-amber-500',
    chip: 'border-amber-300 dark:border-amber-500/40 text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-500/10',
  },
];
const GROUP = Object.fromEntries(GROUPS.map((g) => [g.id, g])) as Record<ReplayGroup, (typeof GROUPS)[number]>;

const TONE_DOT: Record<ReplayEntry['tone'], string | null> = {
  good: 'bg-emerald-500',
  bad: 'bg-rose-500',
  warn: 'bg-amber-500',
  accent: null,
  neutral: null,
};

const TONE_TEXT: Record<ReplayEntry['tone'], string> = {
  good: 'text-emerald-700 dark:text-emerald-400',
  bad: 'text-rose-700 dark:text-rose-400',
  warn: 'text-amber-700 dark:text-amber-400',
  accent: 'text-zinc-900 dark:text-zinc-100',
  neutral: 'text-zinc-700 dark:text-zinc-300',
};

// Everything that happened in a live session, on one scrubbable timeline:
// saves with their diffs, test runs, the dev servers and preview, the AI
// assistant (prompts by mode, replies, proposed edits and what became of
// them), the interviewer chat, and stage changes including the change
// request. Filter by type; drag the scrubber (or step) to walk the round.
export function SessionReplay({ sessionId }: { sessionId: string }) {
  const [replay, setReplay] = useState<Replay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<ReplayGroup>>(new Set());
  const [cursor, setCursor] = useState<number | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const list = useRef<HTMLOListElement>(null);
  // Scrolling follows the scrubber, not clicks on a row (that row is in view).
  const follow = useRef(false);

  useEffect(() => {
    getSessionReplay(sessionId).then(setReplay, (err) =>
      setError(err instanceof Error ? err.message : 'Could not load the replay.'),
    );
  }, [sessionId]);

  const entries = replay?.entries ?? [];
  const counts = useMemo(() => {
    const out = {} as Record<ReplayGroup, number>;
    for (const e of entries) out[e.group] = (out[e.group] ?? 0) + 1;
    return out;
  }, [entries]);
  const shown = useMemo(
    () => entries.map((e, i) => ({ e, i })).filter(({ e }) => !hidden.has(e.group)),
    [entries, hidden],
  );
  // The moment the cursor is on: the last shown entry at or before it.
  const current = useMemo(() => {
    if (cursor == null) return null;
    let at: number | null = null;
    for (const { e, i } of shown) if ((e.t ?? 0) <= cursor) at = i;
    return at;
  }, [shown, cursor]);

  useEffect(() => {
    if (!follow.current || current == null) return;
    follow.current = false;
    const row = list.current?.querySelector<HTMLElement>(`[data-index="${current}"]`);
    const box = list.current;
    if (row && box) box.scrollTop = row.offsetTop - box.offsetTop - box.clientHeight / 3;
  }, [current]);

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!replay) return <p className="font-mono text-sm text-zinc-500">Loading the replay…</p>;
  if (entries.length === 0) return <p className="text-sm text-zinc-500">Nothing was recorded in this session.</p>;

  const duration = Math.max(1, replay.durationS);
  const pct = (t: number | null) => `${Math.min(100, ((t ?? 0) / duration) * 100)}%`;

  function scrub(t: number) {
    follow.current = true;
    setCursor(t);
  }

  function step(direction: 1 | -1) {
    if (shown.length === 0) return;
    const index = current == null ? -1 : shown.findIndex(({ i }) => i === current);
    const next = shown[Math.min(shown.length - 1, Math.max(0, index + direction))];
    scrub(next.e.t ?? 0);
  }

  function toggleGroup(group: ReplayGroup) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  }

  function toggleRow(index: number, t: number | null) {
    setCursor(t ?? 0);
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {replay.metrics.length > 0 && (
        <div className={`${CARD} px-4 py-3`}>
          <p className={SECTION_TITLE}>ROUND METRICS</p>
          <ul className="flex flex-col gap-1.5 text-sm text-zinc-700 dark:text-zinc-300">
            {replay.metrics.map((line, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-zinc-400 dark:text-zinc-600" aria-hidden>
                  ·
                </span>
                <span className="min-w-0 break-words">{line}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={`${CARD} flex flex-col`}>
        <div className="px-4 pt-3 pb-3 flex flex-col gap-3 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show event types">
            {GROUPS.filter((g) => counts[g.id]).map((g) => {
              const on = !hidden.has(g.id);
              return (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => toggleGroup(g.id)}
                  aria-pressed={on}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                    on
                      ? g.chip
                      : 'border-zinc-200 dark:border-zinc-800 text-zinc-400 dark:text-zinc-600 line-through decoration-zinc-300 dark:decoration-zinc-700'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${on ? g.dot : 'bg-zinc-300 dark:bg-zinc-700'}`} aria-hidden />
                  {g.label}
                  <span className="font-mono tabular-nums opacity-70">{counts[g.id]}</span>
                </button>
              );
            })}
          </div>

          <div className="flex flex-col gap-1">
            <div className="relative h-7" aria-hidden>
              <div className="absolute inset-x-0 top-1/2 h-px bg-zinc-200 dark:bg-zinc-800" />
              {replay.changeRequestS != null && (
                <div
                  className="absolute top-0 bottom-0 w-0.5 -ml-px bg-amber-500"
                  style={{ left: pct(replay.changeRequestS) }}
                  title={`Change request at ${formatClock(replay.changeRequestS)}`}
                />
              )}
              {shown.map(({ e, i }) => (
                <span
                  key={i}
                  className={`absolute ${GROUP[e.group].dot} ${
                    current === i ? 'top-0 bottom-0 w-[3px] -ml-px' : 'top-1.5 bottom-1.5 w-px opacity-60'
                  }`}
                  style={{ left: pct(e.t) }}
                />
              ))}
              {cursor != null && (
                <div
                  className="absolute -top-0.5 -bottom-0.5 w-0.5 -ml-px rounded bg-zinc-900 dark:bg-white"
                  style={{ left: pct(cursor) }}
                />
              )}
            </div>
            <input
              type="range"
              min={0}
              max={Math.ceil(duration)}
              step={1}
              value={cursor ?? 0}
              onChange={(ev) => scrub(Number(ev.target.value))}
              aria-label="Scrub through the round"
              aria-valuetext={formatClock(cursor ?? 0)}
              className="w-full accent-indigo-500 dark:[color-scheme:dark]"
            />
            <div className="flex items-center gap-2 font-mono text-xs text-zinc-500 tabular-nums">
              <span>00:00</span>
              {replay.changeRequestS != null && (
                <span className="text-amber-600 dark:text-amber-400">
                  change request {formatClock(replay.changeRequestS)}
                </span>
              )}
              <span className="ml-auto">{formatClock(duration)}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => step(-1)}
              className="px-2.5 py-1 text-xs rounded-md border border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
            >
              &lsaquo; Previous
            </button>
            <button
              type="button"
              onClick={() => step(1)}
              className="px-2.5 py-1 text-xs rounded-md border border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
            >
              Next &rsaquo;
            </button>
            <span className="ml-auto font-mono text-xs text-zinc-500 tabular-nums">
              {cursor == null ? `${shown.length} of ${entries.length} events` : `at ${formatClock(cursor)}`}
            </span>
          </div>
        </div>

        <ol ref={list} className="relative max-h-[36rem] overflow-y-auto py-1">
          {shown.length === 0 && <li className="px-4 py-6 text-sm text-zinc-500">Every type is filtered out.</li>}
          {shown.map(({ e, i }) => (
            <ReplayRow
              key={i}
              index={i}
              entry={e}
              open={open.has(i)}
              current={current === i}
              later={cursor != null && (e.t ?? 0) > cursor}
              onToggle={() => toggleRow(i, e.t)}
            />
          ))}
        </ol>
      </div>
    </div>
  );
}

function ReplayRow({
  index,
  entry,
  open,
  current,
  later,
  onToggle,
}: {
  index: number;
  entry: ReplayEntry;
  open: boolean;
  current: boolean;
  later: boolean;
  onToggle: () => void;
}) {
  const expandable = Boolean(entry.detail || entry.diff);
  const dot = TONE_DOT[entry.tone] ?? GROUP[entry.group].dot;
  const chips = metaChips(entry);
  return (
    <li
      data-index={index}
      className={`border-l-2 ${current ? 'border-indigo-500 bg-indigo-50/60 dark:bg-indigo-500/10' : 'border-transparent'} ${
        later ? 'opacity-45' : ''
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expandable ? open : undefined}
        className="w-full grid grid-cols-[3.25rem_0.75rem_1fr] items-start gap-x-2 px-3 sm:px-4 py-1.5 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
      >
        <span className="font-mono text-xs leading-5 text-zinc-400 tabular-nums">
          {entry.t == null ? '--:--' : formatClock(entry.t)}
        </span>
        <span className="flex h-5 items-center justify-center" aria-hidden>
          <span className={`w-2 h-2 rounded-full ${dot}`} />
        </span>
        <span className="min-w-0 flex flex-col gap-0.5">
          <span className="flex items-baseline gap-2 flex-wrap">
            <span
              className={`min-w-0 break-words text-sm leading-5 ${TONE_TEXT[entry.tone]} ${
                entry.kind === 'command_run' ? 'font-mono text-xs' : ''
              }`}
            >
              {entry.title}
            </span>
            {chips.map((chip) => (
              <span
                key={chip}
                className="font-mono text-[0.68rem] leading-4 px-1.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 whitespace-nowrap"
              >
                {chip}
              </span>
            ))}
            {expandable && (
              <span className="ml-auto text-xs text-zinc-400 shrink-0">{open ? 'Hide' : entry.diff ? 'Diff' : 'Show'}</span>
            )}
          </span>
          {entry.detail && !open && (
            <span className="text-xs text-zinc-500 line-clamp-1 break-all sm:break-words">{entry.detail}</span>
          )}
        </span>
      </button>
      {open && expandable && (
        <div className="pl-3 sm:pl-[6rem] pr-3 sm:pr-4 pb-3 flex flex-col gap-2">
          {entry.detail && (
            <p className="text-sm leading-relaxed whitespace-pre-wrap break-words text-zinc-700 dark:text-zinc-300">
              {entry.detail}
            </p>
          )}
          {entry.diff && (
            <div className="rounded-md border border-zinc-200 dark:border-zinc-800 overflow-auto max-h-80">
              <DiffView diff={entry.diff} />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function metaChips(entry: ReplayEntry): string[] {
  const m = entry.meta;
  const chips: string[] = [];
  if (entry.kind === 'file_saved' || entry.kind === 'assistant_edit_proposed') {
    chips.push(`+${m.added ?? 0} −${m.removed ?? 0}`);
  }
  if (entry.kind === 'assistant_edit_proposed') chips.push(String(m.outcome));
  if (entry.kind === 'assistant_prompt' || entry.kind === 'assistant_response') chips.push(String(m.mode));
  return chips;
}
