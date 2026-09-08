'use client';

import { FocusMinutes, Pomodoro, PomodoroMode } from '../lib/usePomodoro';

const ACCENT: Record<
  PomodoroMode,
  { label: string; ring: string; pill: string; glow: string }
> = {
  focus: {
    label: 'Focus',
    ring: 'stroke-indigo-500 dark:stroke-indigo-400',
    pill: 'bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 border-indigo-300 dark:border-indigo-500/40',
    glow: 'text-indigo-600 dark:text-indigo-400',
  },
  short: {
    label: 'Short Break',
    ring: 'stroke-emerald-500 dark:stroke-emerald-400',
    pill: 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-500/40',
    glow: 'text-emerald-600 dark:text-emerald-400',
  },
  long: {
    label: 'Long Break',
    ring: 'stroke-amber-500 dark:stroke-amber-400',
    pill: 'bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-500/40',
    glow: 'text-amber-600 dark:text-amber-400',
  },
};

const MODES: PomodoroMode[] = ['focus', 'short', 'long'];

function formatClock(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

const RING_R = 120;
const RING_C = 2 * Math.PI * RING_R;

export function PomodoroTab({
  mode,
  focusMin,
  focusOptions,
  secondsLeft,
  totalSeconds,
  isRunning,
  justCompleted,
  start,
  pause,
  reset,
  setMode,
  setFocusMin,
}: Pomodoro) {
  const accent = ACCENT[mode];
  const fraction = totalSeconds > 0 ? secondsLeft / totalSeconds : 0;
  const dashOffset = RING_C * (1 - fraction);

  return (
    <div className="flex flex-col items-center gap-8 max-w-md mx-auto py-4">
      {/* Mode selector */}
      <div className="flex gap-1 rounded-xl border border-zinc-200 dark:border-zinc-800 p-1">
        {MODES.map((m) => {
          const active = m === mode;
          return (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                active
                  ? ACCENT[m].pill
                  : 'border-transparent text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200'
              }`}
            >
              {ACCENT[m].label}
            </button>
          );
        })}
      </div>

      {/* Ring + countdown */}
      <div className="relative w-[260px] h-[260px]">
        <svg viewBox="0 0 260 260" className="w-full h-full -rotate-90">
          <circle
            cx="130"
            cy="130"
            r={RING_R}
            fill="none"
            strokeWidth="8"
            className="stroke-zinc-200 dark:stroke-zinc-800"
          />
          <circle
            cx="130"
            cy="130"
            r={RING_R}
            fill="none"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={RING_C}
            strokeDashoffset={dashOffset}
            className={`${accent.ring} transition-[stroke-dashoffset] duration-500 ease-linear`}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-6xl font-bold tabular-nums text-zinc-900 dark:text-white">
            {formatClock(secondsLeft)}
          </span>
          <span className={`mt-1 font-mono text-xs tracking-widest uppercase ${accent.glow}`}>
            {justCompleted ? "Time's up" : accent.label}
          </span>
        </div>
      </div>

      {/* Focus-length selector (focus mode only) */}
      <div className="h-9 flex items-center">
        {mode === 'focus' ? (
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs tracking-widest text-zinc-500">LENGTH</span>
            <div className="flex gap-1">
              {focusOptions.map((min) => {
                const active = min === focusMin;
                return (
                  <button
                    key={min}
                    onClick={() => setFocusMin(min as FocusMinutes)}
                    disabled={isRunning}
                    className={`px-3 py-1.5 rounded-lg text-sm font-mono border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                      active
                        ? 'bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 border-indigo-300 dark:border-indigo-500/40'
                        : 'border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-400 hover:border-zinc-300 dark:hover:border-zinc-700'
                    }`}
                  >
                    {min}m
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3">
        <button
          onClick={isRunning ? pause : start}
          disabled={!isRunning && secondsLeft === 0}
          className="px-8 py-2.5 rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? 'Pause' : 'Start'}
        </button>
        <button
          onClick={reset}
          className="px-6 py-2.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:border-zinc-300 dark:hover:border-zinc-700 font-medium transition-colors"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
