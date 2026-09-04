export interface Block {
  taskId: string;
  title: string;
  start: string;
  end: string;
  category: string | null;
  priority: string | null;
}

export interface TaskRow {
  id: string;
  name: string;
  category: string;
  priority: string;
  status: string;
  estDurationMin: number;
  scheduledTime: string | null;
  plannedDate: string | null;
  fixedTime: string | null;
  preferredWindow: string | null;
  dueDate: string | null;
  recurs: string | null;
  recurDay: string | null;
  applicationId: string | null;
  interviewId: string | null;
}

export interface PlanResponse {
  day: string;
  brief: string;
  blocks: Block[];
  unplaced: TaskRow[];
  agentBlockCount: number;
}

export interface CategoryWeight {
  category: string;
  rank: number;
}

export interface Application {
  id: string;
  company: string;
  role: string;
  stage: string;
  appliedAt: string | null;
  nextInterviewAt: string | null;
  notes: string | null;
}

export interface Interview {
  id: string;
  applicationId: string;
  company: string | null;
  role: string | null;
  category: string;
  scheduledAt: string;
  notes: string | null;
  syncedToCalendar: boolean;
}

export interface Proposal {
  type: 'propose_duration_change' | 'propose_new_task' | 'propose_reprioritization';
  id: string;
  reason: string;
  [key: string]: unknown;
}

export interface ChatResponse {
  explanation: string;
  proposals: Proposal[];
  history: unknown[];
}

export interface ChatConfirmResponse {
  applied: unknown[];
  plan: PlanResponse;
}

// The 5 ranked interview-prep categories, plus the 2 non-prep ones. Mirrors
// dayline.models.Category - keep in sync by hand.
export const PREP_CATEGORIES = [
  'AI Coding - React/Python',
  'AI Coding - DSA',
  'Behavioral',
  'System Design',
  'Leetcode',
] as const;

export const ALL_CATEGORIES = [...PREP_CATEGORIES, 'Errand', 'Other'] as const;

export const PRIORITIES = ['P0', 'P1', 'P2', 'P3'] as const;

export const RECURRENCES = ['Daily', 'Weekdays', 'Weekly'] as const;

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function checkOk(res: Response, message: string): Promise<Response> {
  if (!res.ok) throw new Error(message);
  return res;
}

// Compute (and commit) the plan for a day. Mirrors run_daily_plan's own
// idempotency: calling this again for the same day reconciles, not duplicates.
export async function planDay(day: string): Promise<PlanResponse> {
  const res = await fetch(`${API}/api/plan?day=${day}`, {
    method: 'POST',
    cache: 'no-store',
  });
  return (await checkOk(res, 'Failed to plan day')).json();
}

// Current tasks (with status/scheduled time) for a day's store.
export async function getTasks(day: string): Promise<TaskRow[]> {
  const res = await fetch(`${API}/api/tasks?day=${day}`, { cache: 'no-store' });
  return (await checkOk(res, 'Failed to load tasks')).json();
}

export interface CreateTaskInput {
  name: string;
  category: string;
  estDurationMin: number;
  priority?: string;
  plannedDate?: string | null;
  fixedTime?: string | null;
  recurs?: string;
  recurDay?: string;
  applicationId?: string | null;
  interviewId?: string | null;
}

export async function createTask(input: CreateTaskInput): Promise<TaskRow> {
  const res = await fetch(`${API}/api/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to create task')).json();
}

export interface UpdateTaskInput {
  estDurationMin?: number;
  priority?: string;
  plannedDate?: string | null;
  category?: string;
  status?: string;
}

export async function updateTask(taskId: string, input: UpdateTaskInput): Promise<TaskRow> {
  const res = await fetch(`${API}/api/tasks/${taskId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to update task')).json();
}

export async function getCategoryWeights(): Promise<CategoryWeight[]> {
  const res = await fetch(`${API}/api/category-weights`, { cache: 'no-store' });
  return (await checkOk(res, 'Failed to load category weights')).json();
}

export async function putCategoryWeights(weights: CategoryWeight[]): Promise<CategoryWeight[]> {
  const res = await fetch(`${API}/api/category-weights`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(weights),
  });
  return (await checkOk(res, 'Failed to save category weights')).json();
}

export async function applyCategoryWeights(): Promise<{ updated: number }> {
  const res = await fetch(`${API}/api/category-weights/apply`, { method: 'POST' });
  return (await checkOk(res, 'Failed to apply category weights')).json();
}

export async function getUpcomingInterviews(): Promise<Interview[]> {
  const res = await fetch(`${API}/api/interviews?upcoming=true`, { cache: 'no-store' });
  return (await checkOk(res, 'Failed to load interviews')).json();
}

export interface CreateInterviewInput {
  applicationId: string;
  category: string;
  scheduledAt: string;
  notes?: string;
}

export async function createInterview(input: CreateInterviewInput): Promise<Interview> {
  const res = await fetch(`${API}/api/interviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to create interview')).json();
}

export async function deleteInterview(interviewId: string): Promise<void> {
  const res = await fetch(`${API}/api/interviews/${interviewId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete interview');
}

export interface CalendarStatus {
  connected: boolean;
}

export async function getCalendarStatus(): Promise<CalendarStatus> {
  const res = await fetch(`${API}/api/calendar/status`, { cache: 'no-store' });
  return (await checkOk(res, 'Failed to load calendar status')).json();
}

// Runs the (one-time) Google OAuth flow server-side - on failure, surfaces
// the backend's exact setup-gap message (e.g. missing credentials.json)
// rather than a generic error, since that message tells the user what to do.
export async function connectCalendar(): Promise<CalendarStatus> {
  const res = await fetch(`${API}/api/calendar/connect`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? 'Failed to connect Google Calendar');
  }
  return res.json();
}

export async function syncInterviewsToCalendar(): Promise<{ synced: number }> {
  const res = await fetch(`${API}/api/calendar/sync-interviews`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? 'Failed to sync interviews');
  }
  return res.json();
}

export interface AgendaItem {
  kind: 'interview' | 'event';
  id: string;
  title: string;
  start: string;
  end: string;
  category: string | null;
  company: string | null;
  interviewId: string | null;
}

export interface AgendaResponse {
  googleConnected: boolean;
  items: AgendaItem[];
}

export async function getCalendarAgenda(): Promise<AgendaResponse> {
  const res = await fetch(`${API}/api/calendar/agenda`, { cache: 'no-store' });
  return (await checkOk(res, 'Failed to load calendar agenda')).json();
}

export async function getApplications(): Promise<Application[]> {
  const res = await fetch(`${API}/api/applications`, { cache: 'no-store' });
  return (await checkOk(res, 'Failed to load applications')).json();
}

export interface CreateApplicationInput {
  company: string;
  role: string;
  stage?: string;
}

export async function createApplication(input: CreateApplicationInput): Promise<Application> {
  const res = await fetch(`${API}/api/applications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to create application')).json();
}

export async function sendChatMessage(
  day: string,
  message: string,
  history?: unknown[]
): Promise<ChatResponse> {
  const res = await fetch(`${API}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day, message, history }),
  });
  return (await checkOk(res, 'Failed to reach chat')).json();
}

export async function confirmProposals(
  day: string,
  proposals: Proposal[]
): Promise<ChatConfirmResponse> {
  const res = await fetch(`${API}/api/chat/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day, proposals }),
  });
  return (await checkOk(res, 'Failed to apply proposals')).json();
}
