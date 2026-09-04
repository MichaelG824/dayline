'use client';

import { useState } from 'react';
import {
  Application,
  CategoryWeight,
  Interview,
  PlanResponse,
  TaskRow,
  getApplications,
  getTasks,
  getUpcomingInterviews,
  planDay,
} from '../lib/api';
import { computeDayTasks } from '../lib/dayTasks';
import { Sidebar } from './Sidebar';
import { TasksTab } from './TasksTab';
import { InterviewsTab } from './InterviewsTab';
import { CalendarTab } from './CalendarTab';
import { ChatTab } from './ChatTab';

export type Tab = 'tasks' | 'interviews' | 'calendar' | 'chat';

interface Props {
  initialDay: string;
  initialPlan: PlanResponse;
  initialTasks: TaskRow[];
  initialCategoryWeights: CategoryWeight[];
  initialInterviews: Interview[];
  initialApplications: Application[];
}

function addDays(day: string, delta: number): string {
  const d = new Date(`${day}T00:00:00`);
  d.setDate(d.getDate() + delta);
  return d.toISOString().slice(0, 10);
}

export function AppShell({
  initialDay,
  initialPlan,
  initialTasks,
  initialCategoryWeights,
  initialInterviews,
  initialApplications,
}: Props) {
  const [tab, setTab] = useState<Tab>('tasks');
  const [day, setDay] = useState(initialDay);
  const [plan, setPlan] = useState(initialPlan);
  const [tasks, setTasks] = useState(initialTasks);
  const [categoryWeights, setCategoryWeights] = useState(initialCategoryWeights);
  const [interviews, setInterviews] = useState(initialInterviews);
  const [applications, setApplications] = useState(initialApplications);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshDay(nextDay: string) {
    setLoading(true);
    setError(null);
    try {
      const [nextPlan, nextTasks] = await Promise.all([planDay(nextDay), getTasks(nextDay)]);
      setDay(nextDay);
      setPlan(nextPlan);
      setTasks(nextTasks);
    } catch {
      setError('Could not reach the planner API - is it running on :8000?');
    } finally {
      setLoading(false);
    }
  }

  async function refreshInterviews() {
    const [nextInterviews, nextApplications] = await Promise.all([
      getUpcomingInterviews(),
      getApplications(),
    ]);
    setInterviews(nextInterviews);
    setApplications(nextApplications);
  }

  const dayTasks = computeDayTasks(plan, tasks);

  return (
    <div className="flex min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <Sidebar
        day={day}
        dayTasks={dayTasks}
        categoryWeights={categoryWeights}
        interviews={interviews}
        onNavigateDay={(delta) => refreshDay(addDays(day, delta))}
        onCategoryWeightsChanged={(next) => setCategoryWeights(next)}
        onAppliedToBacklog={() => refreshDay(day)}
        onGoToCalendar={() => setTab('calendar')}
      />
      <main className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800 px-6 py-3">
          <nav className="flex gap-1">
            {(['tasks', 'interviews', 'calendar', 'chat'] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
                  tab === t
                    ? 'bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 border border-indigo-300 dark:border-indigo-500/40'
                    : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200'
                }`}
              >
                {t}
              </button>
            ))}
          </nav>
        </div>

        {error && <p className="px-6 pt-4 text-rose-600 dark:text-rose-400 text-sm">{error}</p>}

        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'tasks' && (
            <TasksTab
              day={day}
              dayTasks={dayTasks}
              categoryWeights={categoryWeights}
              loading={loading}
              onTasksChanged={() => refreshDay(day)}
            />
          )}
          {tab === 'interviews' && (
            <InterviewsTab
              interviews={interviews}
              applications={applications}
              onChanged={refreshInterviews}
            />
          )}
          {tab === 'calendar' && <CalendarTab onSynced={refreshInterviews} />}
          {tab === 'chat' && (
            <ChatTab
              day={day}
              onPlanUpdated={(nextPlan) => {
                setPlan(nextPlan);
                void refreshDay(day);
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}
