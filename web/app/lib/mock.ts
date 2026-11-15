// Mock-interview display constants. ROUND_TYPES / QUESTION_SOURCES mirror
// dayline.models.MockRoundType / MockQuestionSource - keep in sync by hand.

export const ROUND_TYPES = [
  'AI-assisted project',
  'Algorithm',
  'System design',
  'Debugging',
  'Behavioral',
  'Practical coding',
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

// CodeMirror language id for a workspace file, by extension (see
// languageExtensions in components/problems/CodeEditor.tsx).
const EXTENSION_LANGUAGES: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'typescript',
  mts: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  json: 'javascript',
  java: 'java',
  go: 'go',
  rs: 'rust',
  sql: 'sql',
  c: 'cpp',
  cc: 'cpp',
  cpp: 'cpp',
  h: 'cpp',
  hpp: 'cpp',
};

export function languageForPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  return EXTENSION_LANGUAGES[ext] ?? '';
}

// "mm:ss" (or "h:mm:ss") for a number of seconds.
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

export interface FileNode {
  name: string;
  path: string;
  children: FileNode[] | null; // null for files
}

// Nest flat workspace paths into a tree: folders first, then files, by name.
export function buildFileTree(paths: string[]): FileNode[] {
  const root: FileNode = { name: '', path: '', children: [] };
  for (const path of paths) {
    const parts = path.split('/');
    let node = root;
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      const childPath = parts.slice(0, i + 1).join('/');
      let child = node.children!.find((c) => c.name === part && (c.children === null) === isFile);
      if (!child) {
        child = { name: part, path: childPath, children: isFile ? null : [] };
        node.children!.push(child);
      }
      node = child;
    });
  }
  const sort = (nodes: FileNode[]): FileNode[] =>
    nodes
      .sort((a, b) =>
        (a.children === null) === (b.children === null)
          ? a.name.localeCompare(b.name)
          : a.children === null
            ? 1
            : -1,
      )
      .map((n) => (n.children ? { ...n, children: sort(n.children) } : n));
  return sort(root.children!);
}

// Display names for language packs (sandbox/packs/<name>), when the runner's
// own list is not at hand.
const PACK_LABELS: Record<string, string> = { python: 'Python', typescript: 'TypeScript', java: 'Java', go: 'Go' };

export function packLabel(pack: string): string {
  return PACK_LABELS[pack] ?? pack;
}
