import { Problem } from './api';

// Mirrors dayline.models.Difficulty / ProblemStatus - keep in sync by hand.
export const DIFFICULTIES = ['Easy', 'Medium', 'Hard'] as const;
export const PROBLEM_STATUSES = ['To do', 'Attempted', 'Solved', 'Review'] as const;

// LeetCode-style green/amber/red, with -700 text in light mode and -400 in
// dark (same contrast pairing as CATEGORY_META in categories.ts).
export const DIFFICULTY_BADGE: Record<string, string> = {
  Easy: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  Medium: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400',
  Hard: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400',
};

export const STATUS_BADGE: Record<string, string> = {
  'To do': 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300',
  Attempted: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400',
  Solved: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  Review: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400',
};

export const CONFIDENCE_LABELS: Record<number, string> = {
  1: '1 - Shaky',
  2: '2',
  3: '3 - OK',
  4: '4',
  5: '5 - Confident',
};

// Languages offered in the solution editor. `id` is what's stored on
// Solution.language and picks the CodeMirror grammar.
export const LANGUAGES: { id: string; label: string }[] = [
  { id: 'python', label: 'Python' },
  { id: 'javascript', label: 'JavaScript' },
  { id: 'typescript', label: 'TypeScript' },
  { id: 'java', label: 'Java' },
  { id: 'cpp', label: 'C++' },
  { id: 'go', label: 'Go' },
  { id: 'rust', label: 'Rust' },
  { id: 'sql', label: 'SQL' },
  { id: 'plaintext', label: 'Other / Plain text' },
];

export const DEFAULT_LANGUAGE = 'python';

export function languageLabel(id: string): string {
  return LANGUAGES.find((l) => l.id === id)?.label ?? id;
}

// A problem is "due for review" if it's explicitly in Review, or it was
// attempted (not yet solved) more than a week ago.
const REVIEW_STALE_DAYS = 7;

export function isDueForReview(problem: Problem, now: Date = new Date()): boolean {
  if (problem.status === 'Review') return true;
  if (problem.status !== 'Attempted' || !problem.lastAttemptedAt) return false;
  const staleBefore = now.getTime() - REVIEW_STALE_DAYS * 24 * 60 * 60 * 1000;
  return new Date(problem.lastAttemptedAt).getTime() < staleBefore;
}

// "Two Sum" or "1. Two Sum" - the label used in task names and headings.
export function problemLabel(problem: Pick<Problem, 'number' | 'title'>): string {
  return problem.number != null ? `${problem.number}. ${problem.title}` : problem.title;
}

// ISO datetime -> "Oct 27, 2026"
export function formatShortDate(iso: string | null): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}
