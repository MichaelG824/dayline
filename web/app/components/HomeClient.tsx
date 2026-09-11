'use client';

import { useEffect, useState } from 'react';
import {
  Application,
  CategoryWeight,
  Interview,
  PlanResponse,
  TaskRow,
  getApplications,
  getCategoryWeights,
  getTasks,
  getUpcomingInterviews,
  planDay,
} from '../lib/api';
import { AppShell } from './AppShell';

interface Loaded {
  day: string;
  plan: PlanResponse;
  tasks: TaskRow[];
  categoryWeights: CategoryWeight[];
  interviews: Interview[];
  applications: Application[];
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function HomeClient() {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const day = todayIso();
    void Promise.all([
      planDay(day),
      getTasks(day),
      getCategoryWeights(),
      getUpcomingInterviews(),
      getApplications(),
    ])
      .then(([plan, tasks, categoryWeights, interviews, applications]) => {
        setData({ day, plan, tasks, categoryWeights, interviews, applications });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load Dayline');
      });
  }, []);

  if (error) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex items-center justify-center p-6">
        <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-500 flex items-center justify-center">
        <p className="font-mono text-sm">Loading…</p>
      </div>
    );
  }

  return (
    <AppShell
      initialDay={data.day}
      initialPlan={data.plan}
      initialTasks={data.tasks}
      initialCategoryWeights={data.categoryWeights}
      initialInterviews={data.interviews}
      initialApplications={data.applications}
    />
  );
}
