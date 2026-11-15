'use client';

import { useEffect, useState } from 'react';
import { GeneratedProjectSummary, getGeneratedProjects } from '../../lib/api';
import { progressLabel, stackLabel } from '../../lib/generated';
import { formatShortDate } from '../../lib/problems';
import { CARD, Pill, SECTION_TITLE } from './ui';

// Refresh while something is generating, so its phase stays current.
const POLL_MS = 3000;

function StatusPill({ project }: { project: GeneratedProjectSummary }) {
  switch (project.status) {
    case 'generating':
      return (
        <Pill className="gap-1.5 !bg-indigo-50 !text-indigo-700 dark:!bg-indigo-500/15 dark:!text-indigo-300">
          <span className="h-2.5 w-2.5 rounded-full border-[1.5px] border-indigo-300 dark:border-indigo-500/40 border-t-indigo-600 dark:border-t-indigo-300 animate-spin" />
          {progressLabel(project.progress)}
        </Pill>
      );
    case 'ready':
      return (
        <Pill className="!bg-emerald-100 dark:!bg-emerald-500/15 !text-emerald-700 dark:!text-emerald-300">
          Ready
        </Pill>
      );
    case 'failed':
      return <Pill className="!bg-rose-100 dark:!bg-rose-500/15 !text-rose-700 dark:!text-rose-300">Failed</Pill>;
    default:
      return <Pill>Cancelled</Pill>;
  }
}

// The candidate's generated rounds, newest first. Renders nothing when there
// are none (the Practice header offers to generate one).
export function GeneratedList({ onOpen }: { onOpen: (projectId: string) => void }) {
  const [projects, setProjects] = useState<GeneratedProjectSummary[] | null>(null);
  const generating = projects?.some((p) => p.status === 'generating') ?? false;

  useEffect(() => {
    getGeneratedProjects().then(setProjects, () => setProjects([]));
  }, []);

  useEffect(() => {
    if (!generating) return;
    const timer = setInterval(() => {
      getGeneratedProjects().then(setProjects, () => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [generating]);

  if (!projects?.length) return null;
  return (
    <section className="flex flex-col gap-2">
      <p className={`${SECTION_TITLE} !mb-0`}>GENERATED ROUNDS</p>
      {projects.map((p) => (
        <button
          key={p.id}
          onClick={() => onOpen(p.id)}
          className={`${CARD} flex items-center gap-3 px-4 py-3 text-left hover:border-zinc-300 dark:hover:border-zinc-700`}
        >
          <span className="flex-1 min-w-0 flex flex-col gap-0.5">
            <span className="truncate text-sm font-medium">{p.title || p.prompt}</span>
            {p.status === 'ready' && p.summary && (
              <span className="truncate text-xs text-zinc-500">{p.summary}</span>
            )}
          </span>
          <span className="hidden sm:inline-flex">
            <Pill>{stackLabel(p.stack)}</Pill>
          </span>
          <StatusPill project={p} />
          <span className="hidden sm:inline font-mono text-xs text-zinc-500">
            {p.createdAt ? formatShortDate(p.createdAt) : ''}
          </span>
        </button>
      ))}
    </section>
  );
}
