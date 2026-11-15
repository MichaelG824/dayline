// Generated practice projects: display constants and the import limits.
// The limits mirror dayline.mock.project_spec (the server enforces them too)
// - keep in sync by hand.

import type { Difficulty, GeneratedStack, GenerationPhase, GenerationProgress } from './api';

export const STACKS: { id: GeneratedStack; label: string; blurb: string }[] = [
  { id: 'next-nest', label: 'Next.js + NestJS', blurb: 'React front end, Nest API, Vitest' },
  { id: 'rails', label: 'Rails', blurb: 'Rails 8, SQLite, server-rendered views, Minitest' },
];

export const DIFFICULTIES: Difficulty[] = ['easy', 'medium', 'hard'];

export const MIN_DURATION_MIN = 20;
export const MAX_DURATION_MIN = 120;
export const MIN_CHANGE_GAP_MIN = 5;
export const MAX_PROMPT_CHARS = 4000;

export const MAX_CONTEXT_FILES = 10;
export const MAX_CONTEXT_FILE_BYTES = 64 * 1024;
export const MAX_CONTEXT_TOTAL_BYTES = 256 * 1024;
const CONTEXT_EXTENSIONS = new Set(
  (
    'md markdown txt text rst adoc csv tsv log json yml yaml toml ini cfg env xml html htm css ' +
    'scss sql graphql gql proto py rb erb rake js jsx mjs cjs ts tsx go rs java kt kts scala ' +
    'swift c h cc cpp hpp cs php sh bash zsh lua ex exs dart vue svelte'
  ).split(' '),
);
const CONTEXT_NAMES = new Set(['readme', 'dockerfile', 'makefile', 'gemfile', 'procfile']);

// For the file input's picker; the check below is what counts.
export const CONTEXT_ACCEPT = [...CONTEXT_EXTENSIONS].map((ext) => `.${ext}`).join(',');

export function contextFileProblem(name: string, bytes: number, content: string): string | null {
  const dot = name.lastIndexOf('.');
  const known =
    dot > 0 ? CONTEXT_EXTENSIONS.has(name.slice(dot + 1).toLowerCase()) : CONTEXT_NAMES.has(name.toLowerCase());
  if (!known) return `${name}: only text and code files can be imported`;
  if (bytes > MAX_CONTEXT_FILE_BYTES) return `${name}: files must be under ${MAX_CONTEXT_FILE_BYTES / 1024} KB`;
  if (content.includes('\u0000')) return `${name}: this looks like a binary file, not text`;
  return null;
}

export function formatBytes(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
}

// The steps of a generation, in order, as the progress view lists them.
export const PHASES: { id: GenerationPhase; label: string }[] = [
  { id: 'writing', label: 'Writing the project' },
  { id: 'checking_dependencies', label: 'Checking dependencies' },
  { id: 'booting', label: 'Booting the app' },
  { id: 'running_tests', label: 'Running the tests' },
];

// Which listed step a progress report is on ("repairing" rewrites the project).
export function phaseIndex(progress: GenerationProgress): number {
  const phase = progress.phase === 'repairing' ? 'writing' : progress.phase;
  const index = PHASES.findIndex((p) => p.id === phase);
  return index < 0 ? 0 : index;
}

export const MAX_REPAIRS = 3;

export function progressLabel(progress: GenerationProgress): string {
  const step = PHASES[phaseIndex(progress)].label;
  const attempt = progress.attempt ?? 0;
  if (progress.phase === 'repairing') return `Repairing ${attempt}/${MAX_REPAIRS}`;
  return attempt > 0 ? `${step} (repair ${attempt}/${MAX_REPAIRS})` : step;
}

export function stackLabel(stack: string): string {
  return STACKS.find((s) => s.id === stack)?.label ?? stack;
}
