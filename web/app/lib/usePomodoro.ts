'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type PomodoroMode = 'focus' | 'short' | 'long';
export type FocusMinutes = 25 | 50 | 60;

const FOCUS_OPTIONS: FocusMinutes[] = [25, 50, 60];
const SHORT_BREAK_MIN = 5;
const LONG_BREAK_MIN = 15;
const DEFAULT_FOCUS: FocusMinutes = 60;
const FOCUS_PREF_KEY = 'dayline-pomodoro-focus';

export interface Pomodoro {
  mode: PomodoroMode;
  focusMin: FocusMinutes;
  focusOptions: FocusMinutes[];
  secondsLeft: number;
  totalSeconds: number;
  isRunning: boolean;
  justCompleted: boolean;
  start: () => void;
  pause: () => void;
  reset: () => void;
  setMode: (mode: PomodoroMode) => void;
  setFocusMin: (min: FocusMinutes) => void;
}

function durationFor(mode: PomodoroMode, focusMin: FocusMinutes): number {
  if (mode === 'short') return SHORT_BREAK_MIN * 60;
  if (mode === 'long') return LONG_BREAK_MIN * 60;
  return focusMin * 60;
}

// A short two-note chime generated on the fly, so there's no audio asset to
// ship. Wrapped so a browser that blocks/lacks AudioContext just stays silent.
function playChime() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const notes = [880, 1174.66];
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const startAt = ctx.currentTime + i * 0.18;
      gain.gain.setValueAtTime(0.0001, startAt);
      gain.gain.exponentialRampToValueAtTime(0.25, startAt + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startAt + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(startAt);
      osc.stop(startAt + 0.4);
    });
    setTimeout(() => void ctx.close().catch(() => {}), 1200);
  } catch {
    // no-op: audio is a nicety, never required
  }
}

function formatTitle(secondsLeft: number, mode: PomodoroMode): string {
  const m = Math.floor(secondsLeft / 60);
  const s = secondsLeft % 60;
  const label = mode === 'focus' ? 'Focus' : mode === 'short' ? 'Break' : 'Long break';
  return `${m}:${String(s).padStart(2, '0')} · ${label} - Dayline`;
}

// Owns all Pomodoro state. Lives in AppShell (always mounted) so the timer
// keeps running when the user switches to another tab. Ticking is driven off
// an absolute end-timestamp rather than a decrementing counter, so it never
// drifts and recovers correctly after a background tab throttles the interval.
export function usePomodoro(): Pomodoro {
  const [focusMin, setFocusMinState] = useState<FocusMinutes>(DEFAULT_FOCUS);
  const [mode, setModeState] = useState<PomodoroMode>('focus');
  const [secondsLeft, setSecondsLeft] = useState<number>(DEFAULT_FOCUS * 60);
  const [isRunning, setIsRunning] = useState(false);
  const [justCompleted, setJustCompleted] = useState(false);

  const endsAtRef = useRef<number | null>(null);
  const baseTitleRef = useRef<string | null>(null);

  // Restore the saved focus-length preference after mount (never during
  // render), mirroring ThemeToggle's hydration-safe pattern. At mount the
  // timer is always idle on the focus mode, so it's safe to set the clock too.
  useEffect(() => {
    try {
      const saved = Number(localStorage.getItem(FOCUS_PREF_KEY));
      if (FOCUS_OPTIONS.includes(saved as FocusMinutes)) {
        setFocusMinState(saved as FocusMinutes);
        setSecondsLeft(saved * 60);
      }
    } catch {
      // ignore unreadable storage
    }
    // run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The tick: while running, recompute the remaining time from the target
  // end-timestamp and stop cleanly at zero.
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => {
      const endsAt = endsAtRef.current;
      if (endsAt === null) return;
      const left = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
      setSecondsLeft(left);
      if (left === 0) {
        endsAtRef.current = null;
        setIsRunning(false);
        setJustCompleted(true);
        playChime();
      }
    }, 250);
    return () => clearInterval(id);
  }, [isRunning]);

  // Reflect the live countdown in the browser tab title while running, and
  // restore the original title whenever the timer stops or unmounts.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (isRunning) {
      if (baseTitleRef.current === null) baseTitleRef.current = document.title;
      document.title = formatTitle(secondsLeft, mode);
    } else if (baseTitleRef.current !== null) {
      document.title = baseTitleRef.current;
      baseTitleRef.current = null;
    }
    return () => {
      if (baseTitleRef.current !== null) {
        document.title = baseTitleRef.current;
        baseTitleRef.current = null;
      }
    };
  }, [isRunning, secondsLeft, mode]);

  const start = useCallback(() => {
    setSecondsLeft((left) => {
      if (left <= 0) return left;
      endsAtRef.current = Date.now() + left * 1000;
      setIsRunning(true);
      setJustCompleted(false);
      return left;
    });
  }, []);

  const pause = useCallback(() => {
    endsAtRef.current = null;
    setIsRunning(false);
  }, []);

  const reset = useCallback(() => {
    endsAtRef.current = null;
    setIsRunning(false);
    setJustCompleted(false);
    setSecondsLeft(durationFor(mode, focusMin));
  }, [mode, focusMin]);

  const setMode = useCallback(
    (next: PomodoroMode) => {
      endsAtRef.current = null;
      setIsRunning(false);
      setJustCompleted(false);
      setModeState(next);
      setSecondsLeft(durationFor(next, focusMin));
    },
    [focusMin]
  );

  const setFocusMin = useCallback(
    (next: FocusMinutes) => {
      setFocusMinState(next);
      try {
        localStorage.setItem(FOCUS_PREF_KEY, String(next));
      } catch {
        // ignore unwritable storage
      }
      // Only re-length the clock when we're sitting idle on the focus mode;
      // never yank time out from under a running timer or an active break.
      if (mode === 'focus' && endsAtRef.current === null) {
        setIsRunning(false);
        setJustCompleted(false);
        setSecondsLeft(next * 60);
      }
    },
    [mode]
  );

  return {
    mode,
    focusMin,
    focusOptions: FOCUS_OPTIONS,
    secondsLeft,
    totalSeconds: durationFor(mode, focusMin),
    isRunning,
    justCompleted,
    start,
    pause,
    reset,
    setMode,
    setFocusMin,
  };
}
