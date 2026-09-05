import {
  getApplications,
  getCategoryWeights,
  getTasks,
  getUpcomingInterviews,
  planDay,
} from './lib/api';
import { AppShell } from './components/AppShell';

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

// The home page (server component): computes today's plan on the server
// before the page ever reaches the browser, then hands it to the client
// shell that owns the sidebar, tabs, and all interactive state.
export default async function HomePage() {
  const day = todayIso();
  const [plan, tasks, categoryWeights, interviews, applications] = await Promise.all([
    planDay(day),
    getTasks(day),
    getCategoryWeights(),
    getUpcomingInterviews(),
    getApplications(),
  ]);

  return (
    <AppShell
      initialDay={day}
      initialPlan={plan}
      initialTasks={tasks}
      initialCategoryWeights={categoryWeights}
      initialInterviews={interviews}
      initialApplications={applications}
    />
  );
}
