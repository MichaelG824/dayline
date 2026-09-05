// Display metadata for each Category value - short label + accent color.
// Mirrors dayline.models.Category; keep in sync by hand.

export interface CategoryMeta {
  short: string;
  dot: string;
  /** Combined light + dark text color classes, e.g. "text-indigo-600 dark:text-indigo-400". */
  text: string;
}

// The -400 shades read well on the dark background but are too low-contrast
// on white, so each category pairs a light-mode (-600) and dark-mode (-400)
// text color rather than sharing one across both themes.
export const CATEGORY_META: Record<string, CategoryMeta> = {
  'AI Coding - React/Python': {
    short: 'AI React/Py',
    dot: 'bg-indigo-400',
    text: 'text-indigo-600 dark:text-indigo-400',
  },
  'AI Coding - DSA': {
    short: 'AI DSA',
    dot: 'bg-violet-400',
    text: 'text-violet-600 dark:text-violet-400',
  },
  Behavioral: {
    short: 'Behavioral',
    dot: 'bg-emerald-400',
    text: 'text-emerald-600 dark:text-emerald-400',
  },
  'System Design': {
    short: 'Sys Design',
    dot: 'bg-amber-400',
    text: 'text-amber-600 dark:text-amber-400',
  },
  Leetcode: { short: 'DSA Pure', dot: 'bg-rose-400', text: 'text-rose-600 dark:text-rose-400' },
  Errand: { short: 'Errand', dot: 'bg-zinc-500', text: 'text-zinc-500 dark:text-zinc-400' },
  Other: { short: 'Other', dot: 'bg-zinc-500', text: 'text-zinc-500 dark:text-zinc-400' },
};

export function categoryMeta(category: string): CategoryMeta {
  return (
    CATEGORY_META[category] ?? {
      short: category,
      dot: 'bg-zinc-500',
      text: 'text-zinc-500 dark:text-zinc-400',
    }
  );
}

export function isMiscCategory(category: string): boolean {
  return category === 'Errand' || category === 'Other';
}

// Prep categories ordered by current focus rank (1-5, unique - no ties, so
// no tie-break needed). Shared by Sidebar (priority list) and TasksTab (group
// rank labels) so both agree on rank numbers.
export function rankCategories(categoryWeights: { category: string; rank: number }[]): string[] {
  return [...categoryWeights].sort((a, b) => a.rank - b.rank).map((w) => w.category);
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}
