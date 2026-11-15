'use client';

import { useEffect, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
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
import { usePomodoro, formatClock } from '../lib/usePomodoro';
import { Sidebar } from './Sidebar';
import { MENU_ICON, NavIcon, Tab, tabLabel } from './SidebarNav';
import { TasksTab } from './TasksTab';
import { InterviewsTab } from './InterviewsTab';
import { ChatTab } from './ChatTab';
import { PomodoroTab } from './PomodoroTab';

// Code-split: CodeMirror + markdown only load once the LeetCode Problems tab opens.
const ProblemsTab = dynamic(() => import('./problems/ProblemsTab').then((m) => m.ProblemsTab), {
  loading: () => <p className="font-mono text-sm text-zinc-500">Loading…</p>,
});

const MockTab = dynamic(() => import('./mock/MockTab').then((m) => m.MockTab), {
  loading: () => <p className="font-mono text-sm text-zinc-500">Loading…</p>,
});

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
  const [openProblemId, setOpenProblemId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const wasNavOpen = useRef(false);
  const pomodoro = usePomodoro();

  // The drawer only exists below lg: close it on Escape, lock the page behind
  // it, and drop it if the window grows into the static-sidebar layout.
  useEffect(() => {
    // Hand focus back to the menu button once <main> is no longer inert.
    if (!navOpen && wasNavOpen.current) menuButtonRef.current?.focus();
    wasNavOpen.current = navOpen;
    if (!navOpen) return;
    const wide = window.matchMedia('(min-width: 1024px)');
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNavOpen(false);
    };
    const onWide = () => {
      if (wide.matches) setNavOpen(false);
    };
    const root = document.documentElement;
    const previousOverflow = root.style.overflow;
    root.style.overflow = 'hidden';
    document.addEventListener('keydown', onKey);
    wide.addEventListener('change', onWide);
    return () => {
      root.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKey);
      wide.removeEventListener('change', onWide);
    };
  }, [navOpen]);

  function selectTab(next: Tab) {
    setTab(next);
    setNavOpen(false);
  }

  async function refreshDay(nextDay: string) {
    setLoading(true);
    setError(null);
    try {
      const [nextPlan, nextTasks] = await Promise.all([planDay(nextDay), getTasks(nextDay)]);
      setDay(nextDay);
      setPlan(nextPlan);
      setTasks(nextTasks);
    } catch {
      setError('Could not reach the planner API.');
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

  function openProblem(problemId: string) {
    setOpenProblemId(problemId);
    selectTab('problems');
  }

  const dayTasks = computeDayTasks(plan, tasks);

  return (
    <div className="flex min-h-dvh bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      {navOpen && (
        <div
          className="fixed inset-0 z-20 bg-zinc-950/40 dark:bg-black/60 lg:hidden"
          onClick={() => setNavOpen(false)}
          aria-hidden="true"
        />
      )}
      <Sidebar
        tab={tab}
        onSelectTab={selectTab}
        pomodoroClock={pomodoro.isRunning ? formatClock(pomodoro.secondsLeft) : null}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        day={day}
        dayTasks={dayTasks}
        categoryWeights={categoryWeights}
        interviews={interviews}
        onNavigateDay={(delta) => refreshDay(addDays(day, delta))}
        onCategoryWeightsChanged={(next) => setCategoryWeights(next)}
        onAppliedToBacklog={() => refreshDay(day)}
        onGoToCalendar={() => selectTab('interviews')}
      />
      <main className="flex-1 flex flex-col min-w-0" inert={navOpen}>
        {/* Below lg the sidebar is a drawer, so this bar is how you reach the nav. */}
        <header className="lg:hidden sticky top-0 z-10 flex items-center gap-3 h-14 px-4 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/90 dark:bg-zinc-950/90 backdrop-blur">
          <button
            ref={menuButtonRef}
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={navOpen}
            aria-controls="app-sidebar"
            className="-ml-1 w-9 h-9 flex items-center justify-center rounded-lg text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-900 focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            <NavIcon d={MENU_ICON} />
          </button>
          <span className="min-w-0 truncate font-semibold">{tabLabel(tab)}</span>
          {pomodoro.isRunning && tab !== 'pomodoro' && (
            <button
              type="button"
              onClick={() => selectTab('pomodoro')}
              aria-label="Open Pomodoro"
              className="ml-auto shrink-0 font-mono text-xs tabular-nums text-emerald-600 dark:text-emerald-400"
            >
              {formatClock(pomodoro.secondsLeft)}
            </button>
          )}
        </header>

        {error && <p className="px-4 sm:px-6 pt-4 text-rose-600 dark:text-rose-400 text-sm">{error}</p>}

        <div className="flex-1 p-4 sm:p-6">
          {tab === 'tasks' && (
            <TasksTab
              day={day}
              dayTasks={dayTasks}
              categoryWeights={categoryWeights}
              loading={loading}
              onTasksChanged={() => refreshDay(day)}
              onOpenProblem={openProblem}
            />
          )}
          {tab === 'problems' && (
            <ProblemsTab
              day={day}
              openProblemId={openProblemId}
              onOpenProblem={setOpenProblemId}
              onTasksChanged={() => refreshDay(day)}
            />
          )}
          {tab === 'mock' && <MockTab day={day} onTasksChanged={() => refreshDay(day)} />}
          {tab === 'interviews' && (
            <InterviewsTab
              interviews={interviews}
              applications={applications}
              onChanged={refreshInterviews}
            />
          )}
          {tab === 'chat' && (
            <ChatTab
              day={day}
              onPlanUpdated={(nextPlan) => {
                setPlan(nextPlan);
                void refreshDay(day);
              }}
            />
          )}
          {tab === 'pomodoro' && <PomodoroTab {...pomodoro} />}
        </div>
      </main>
    </div>
  );
}
