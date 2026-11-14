// Mock-interview display constants. ROUND_TYPES / QUESTION_SOURCES mirror
// dayline.models.MockRoundType / MockQuestionSource - keep in sync by hand.

export const ROUND_TYPES = [
  'AI-assisted project',
  'Algorithm',
  'System design',
  'Debugging',
  'Behavioral',
] as const;

export const QUESTION_SOURCES: { value: string; label: string }[] = [
  { value: 'own', label: 'My interview' },
  { value: '1point3acres', label: '1point3acres' },
  { value: 'other', label: 'Other' },
];

// "zh" -> "Chinese". Falls back to the code if the browser can't name it.
export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

export function sourceLabel(source: string): string {
  return QUESTION_SOURCES.find((s) => s.value === source)?.label ?? source;
}

// Scores are 1-4 per criterion; the overall is a weighted mean.
export const MAX_SCORE = 4;

export const SCORE_LABELS: Record<number, string> = {
  1: 'Not shown',
  2: 'Gaps',
  3: 'Meets the bar',
  4: 'Strong',
};

// Light (-600) and dark (-400) text pairs, like lib/categories.ts.
export function scoreText(score: number): string {
  if (score >= 3.5) return 'text-emerald-600 dark:text-emerald-400';
  if (score >= 2.75) return 'text-indigo-600 dark:text-indigo-400';
  if (score >= 2) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

export function scoreFill(score: number): string {
  if (score >= 3.5) return 'bg-emerald-500';
  if (score >= 2.75) return 'bg-indigo-500';
  if (score >= 2) return 'bg-amber-500';
  return 'bg-rose-500';
}

export function linesToList(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.replace(/^\s*[-*]\s+/, '').trim())
    .filter(Boolean);
}

export function listToLines(items: string[]): string {
  return items.join('\n');
}
