'use client';

import { useCallback, useEffect, useState } from 'react';
import { Problem, ProblemTag, exportProblems, getProblemTags, getProblems, updateProblem } from '../../lib/api';
import { ProblemDetail } from './ProblemDetail';
import { ProblemForm } from './ProblemForm';
import { ProblemList } from './ProblemList';
import { TagManager } from './TagManager';

// Which screen of the tab is showing. The open problem id lives in AppShell
// (so a task's problem link can jump straight here); the rest is local.
type View = { kind: 'list' } | { kind: 'form'; problem?: Problem } | { kind: 'tags' };

interface Props {
  day: string;
  openProblemId: string | null;
  onOpenProblem: (problemId: string | null) => void;
  onTasksChanged: () => void;
}

export function ProblemsTab({ day, openProblemId, onOpenProblem, onTasksChanged }: Props) {
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [tags, setTags] = useState<ProblemTag[]>([]);
  const [view, setView] = useState<View>({ kind: 'list' });
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextProblems, nextTags] = await Promise.all([getProblems(), getProblemTags()]);
      setProblems(nextProblems);
      setTags(nextTags);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load problems.');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function openProblem(problemId: string | null) {
    setView({ kind: 'list' });
    onOpenProblem(problemId);
  }

  async function toggleStar(problem: Problem) {
    await updateProblem(problem.id, { starred: !problem.starred });
    await refresh();
  }

  async function handleExport() {
    const data = await exportProblems();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `dayline-problems-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  if (error && !problems) return <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>;
  if (!problems) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  if (view.kind === 'form') {
    return (
      <ProblemForm
        tags={tags}
        problem={view.problem}
        onCancel={() => setView({ kind: 'list' })}
        onSaved={(saved) => {
          void refresh();
          openProblem(saved.id);
        }}
      />
    );
  }

  if (view.kind === 'tags') {
    return <TagManager tags={tags} onBack={() => setView({ kind: 'list' })} onChanged={() => void refresh()} />;
  }

  if (openProblemId) {
    return (
      <ProblemDetail
        // Remount per problem so detail state never leaks across problems.
        key={openProblemId}
        problemId={openProblemId}
        day={day}
        tags={tags}
        onBack={() => openProblem(null)}
        onEdit={(problem) => setView({ kind: 'form', problem })}
        onChanged={() => void refresh()}
        onDeleted={() => {
          void refresh();
          openProblem(null);
        }}
        onTasksChanged={onTasksChanged}
      />
    );
  }

  return (
    <ProblemList
      problems={problems}
      tags={tags}
      onOpen={(id) => openProblem(id)}
      onNew={() => setView({ kind: 'form' })}
      onManageTags={() => setView({ kind: 'tags' })}
      onToggleStar={(p) => void toggleStar(p)}
      onExport={() => void handleExport()}
    />
  );
}
