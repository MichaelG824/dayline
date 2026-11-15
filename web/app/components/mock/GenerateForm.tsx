'use client';

import { useEffect, useRef, useState } from 'react';
import { Difficulty, GeneratedStack, LiveAvailability, createGeneratedProject, getLiveAvailability } from '../../lib/api';
import {
  CONTEXT_ACCEPT,
  DIFFICULTIES,
  MAX_CONTEXT_FILES,
  MAX_CONTEXT_TOTAL_BYTES,
  MAX_DURATION_MIN,
  MAX_PROMPT_CHARS,
  MIN_CHANGE_GAP_MIN,
  MIN_DURATION_MIN,
  STACKS,
  contextFileProblem,
  formatBytes,
} from '../../lib/generated';
import { BackButton, CARD, ErrorText, FIELD, Label, PRIMARY_BUTTON, QUIET_BUTTON, SECONDARY_BUTTON } from './ui';

interface Props {
  onCancel: () => void;
  onCreated: (projectId: string) => void;
}

interface ContextFile {
  name: string;
  bytes: number;
  content: string;
}

const PLACEHOLDER =
  'e.g. A Next.js + Nest notes app where I add tagging; at 30 minutes they asked me to add filtering by tag.';

// Describe a round, optionally import files for context, and start
// generating a project for it (it is validated in a sandbox before it shows).
export function GenerateForm({ onCancel, onCreated }: Props) {
  const [live, setLive] = useState<LiveAvailability | null>(null);
  const [prompt, setPrompt] = useState('');
  const [stack, setStack] = useState<GeneratedStack>('next-nest');
  const [difficulty, setDifficulty] = useState<Difficulty>('medium');
  const [duration, setDuration] = useState(45);
  const [changeAt, setChangeAt] = useState(30);
  const [files, setFiles] = useState<ContextFile[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getLiveAvailability().then(setLive, () => undefined);
  }, []);

  const totalBytes = files.reduce((sum, f) => sum + f.bytes, 0);
  const latestChange = duration - MIN_CHANGE_GAP_MIN;
  const durationOk = duration >= MIN_DURATION_MIN && duration <= MAX_DURATION_MIN;
  const changeOk = changeAt >= MIN_CHANGE_GAP_MIN && changeAt <= latestChange;
  const pack = live?.packs.find((p) => p.name === stack);
  const blocker = !live
    ? null
    : !live.available
      ? live.reason
      : !pack
        ? 'The sandbox runner has no full-stack packs yet. Redeploy it.'
        : pack.state === 'failed'
          ? `The ${pack.displayName} sandbox image failed to build: ${pack.error}`
          : pack.state !== 'ready'
            ? `The ${pack.displayName} sandbox image is still being built. Try again in a minute.`
            : null;

  async function addFiles(list: FileList | File[]) {
    setFileError(null);
    const next = [...files];
    for (const file of Array.from(list)) {
      if (next.length >= MAX_CONTEXT_FILES) {
        setFileError(`Import at most ${MAX_CONTEXT_FILES} files.`);
        break;
      }
      const content = await file.text();
      const problem = contextFileProblem(file.name, file.size, content);
      if (problem) {
        setFileError(problem);
        continue;
      }
      if (next.reduce((sum, f) => sum + f.bytes, 0) + file.size > MAX_CONTEXT_TOTAL_BYTES) {
        setFileError(`Context files must total under ${MAX_CONTEXT_TOTAL_BYTES / 1024} KB.`);
        break;
      }
      const at = next.findIndex((f) => f.name === file.name);
      const entry = { name: file.name, bytes: file.size, content };
      if (at >= 0) next[at] = entry;
      else next.push(entry);
    }
    setFiles(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) {
      setError('Describe the round first.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const project = await createGeneratedProject({
        prompt,
        stack,
        difficulty,
        durationMin: duration,
        changeRequestMin: changeAt,
        contextFiles: files.map(({ name, content }) => ({ name, content })),
      });
      onCreated(project.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start generating.');
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onCancel}>Practice</BackButton>
        <h2 className="text-lg font-semibold">Generate a practice round</h2>
      </div>
      <p className="text-sm text-zinc-500">
        Describe the round you want to practise. Dayline writes a small full-stack app, the task, and a change
        request the interviewer brings in partway through, then checks all of it in a sandbox before you see it.
        That takes 2 to 5 minutes.
      </p>

      {blocker && <div className={`${CARD} px-4 py-3 text-sm text-amber-700 dark:text-amber-300`}>{blocker}</div>}

      <div>
        <Label htmlFor="g-prompt">The round</Label>
        <textarea
          id="g-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={4}
          maxLength={MAX_PROMPT_CHARS}
          className={`${FIELD} resize-y min-h-[6rem]`}
        />
        <p className="mt-1 text-xs text-zinc-500">
          Say what the app is, what you build, and what changes midway. {prompt.length}/{MAX_PROMPT_CHARS}
        </p>
      </div>

      <fieldset>
        <legend className="block text-xs font-mono text-zinc-500 mb-1">Stack</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {STACKS.map((s) => (
            <label
              key={s.id}
              className={`${CARD} flex items-start gap-3 px-4 py-3 cursor-pointer ${
                stack === s.id
                  ? '!border-indigo-400 dark:!border-indigo-500/70'
                  : 'hover:border-zinc-300 dark:hover:border-zinc-700'
              }`}
            >
              <input
                type="radio"
                name="stack"
                checked={stack === s.id}
                onChange={() => setStack(s.id)}
                className="mt-1 accent-indigo-500"
              />
              <span className="flex flex-col gap-0.5 min-w-0">
                <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{s.label}</span>
                <span className="text-sm text-zinc-500">{s.blurb}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <span className="block text-xs font-mono text-zinc-500 mb-1" id="g-difficulty">
            Difficulty
          </span>
          <div
            role="radiogroup"
            aria-labelledby="g-difficulty"
            className="grid grid-cols-3 rounded-lg border border-zinc-200 dark:border-zinc-800 p-0.5 bg-zinc-50 dark:bg-zinc-950"
          >
            {DIFFICULTIES.map((d) => (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={difficulty === d}
                onClick={() => setDifficulty(d)}
                className={`py-1.5 text-sm rounded-md capitalize ${
                  difficulty === d
                    ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-sm'
                    : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        </div>
        <div>
          <Label htmlFor="g-duration">Round length (minutes)</Label>
          <input
            id="g-duration"
            type="number"
            min={MIN_DURATION_MIN}
            max={MAX_DURATION_MIN}
            step={5}
            value={Number.isNaN(duration) ? '' : duration}
            onChange={(e) => setDuration(e.target.valueAsNumber)}
            className={FIELD}
          />
        </div>
        <div>
          <Label htmlFor="g-change">Change request at (minute)</Label>
          <input
            id="g-change"
            type="number"
            min={MIN_CHANGE_GAP_MIN}
            max={Math.max(MIN_CHANGE_GAP_MIN, latestChange)}
            value={Number.isNaN(changeAt) ? '' : changeAt}
            onChange={(e) => setChangeAt(e.target.valueAsNumber)}
            className={FIELD}
          />
        </div>
      </div>
      {(!durationOk || !changeOk) && (
        <p className="-mt-3 text-xs text-rose-600 dark:text-rose-400">
          {!durationOk
            ? `The round must last ${MIN_DURATION_MIN} to ${MAX_DURATION_MIN} minutes.`
            : `The change request must come between minute ${MIN_CHANGE_GAP_MIN} and minute ${latestChange}.`}
        </p>
      )}

      <div>
        <span className="block text-xs font-mono text-zinc-500 mb-1">Context files (optional)</span>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            void addFiles(e.dataTransfer.files);
          }}
          className={`rounded-lg border border-dashed px-4 py-4 flex flex-col sm:flex-row sm:items-center gap-3 transition-colors ${
            dragging
              ? 'border-indigo-400 bg-indigo-50/60 dark:border-indigo-500/70 dark:bg-indigo-500/10'
              : 'border-zinc-300 dark:border-zinc-700'
          }`}
        >
          <p className="flex-1 text-sm text-zinc-500">
            Past question write-ups, a README, code snippets: text and code files only, up to{' '}
            {MAX_CONTEXT_FILES} files and {MAX_CONTEXT_TOTAL_BYTES / 1024} KB in all. They stay private to you and
            only go to the generator.
          </p>
          <button type="button" onClick={() => picker.current?.click()} className={`${SECONDARY_BUTTON} shrink-0`}>
            Add files
          </button>
          <input
            ref={picker}
            type="file"
            multiple
            accept={CONTEXT_ACCEPT}
            className="hidden"
            onChange={(e) => {
              if (e.target.files) void addFiles(e.target.files);
              e.target.value = '';
            }}
          />
        </div>
        {fileError && <p className="mt-1.5 text-xs text-rose-600 dark:text-rose-400">{fileError}</p>}
        {files.length > 0 && (
          <ul className={`${CARD} mt-2 divide-y divide-zinc-200 dark:divide-zinc-800`}>
            {files.map((f) => (
              <li key={f.name} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="font-mono text-xs text-zinc-800 dark:text-zinc-200 truncate min-w-0 flex-1" title={f.name}>
                  {f.name}
                </span>
                <span className="font-mono text-xs text-zinc-500 shrink-0">{formatBytes(f.bytes)}</span>
                <button
                  type="button"
                  onClick={() => setFiles(files.filter((x) => x.name !== f.name))}
                  className="shrink-0 text-xs text-zinc-500 hover:text-rose-600 dark:hover:text-rose-400"
                  aria-label={`Remove ${f.name}`}
                >
                  Remove
                </button>
              </li>
            ))}
            <li className="px-3 py-1.5 text-xs text-zinc-500">
              {files.length} {files.length === 1 ? 'file' : 'files'} · {formatBytes(totalBytes)} of{' '}
              {MAX_CONTEXT_TOTAL_BYTES / 1024} KB
            </li>
          </ul>
        )}
      </div>

      {error && <ErrorText>{error}</ErrorText>}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting || !prompt.trim() || !durationOk || !changeOk || blocker != null}
          className={PRIMARY_BUTTON}
        >
          {submitting ? 'Starting…' : 'Generate'}
        </button>
        <button type="button" onClick={onCancel} className={QUIET_BUTTON}>
          Cancel
        </button>
      </div>
    </form>
  );
}
