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
  googleEventOwned: boolean;
  hidden: boolean;
}

export type ProposalType =
  | 'propose_duration_change'
  | 'propose_new_task'
  | 'propose_reprioritization'
  | 'propose_preference_update'
  | 'propose_category_rank_change';

export interface Proposal {
  type: ProposalType;
  id: string;
  reason: string;
  [key: string]: unknown;
}

export interface PlannerPreferences {
  peakHours: string | null;
  categoryCaps: Record<string, number>;
  standingRules: string[];
  freeText: string | null;
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

// Same-origin `/api` by default (Next rewrites in dev; Caddy reverse-proxies
// in production). Set NEXT_PUBLIC_API_URL only when the browser must talk to
// a different origin (the old two-port local setup without the rewrite).
const API = process.env.NEXT_PUBLIC_API_URL ?? '';

export interface AuthUser {
  email: string;
  allowed: boolean;
}

function redirectForAuth(status: number): void {
  if (typeof window === 'undefined') return;
  if (status === 401) {
    window.location.replace('/login');
  } else if (status === 403) {
    window.location.replace('/not-allowed');
  }
}

async function checkOk(res: Response, message: string): Promise<Response> {
  if (res.status === 401 || res.status === 403) {
    redirectForAuth(res.status);
  }
  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // non-JSON error body - keep the generic message
    }
    throw new Error(detail || message);
  }
  return res;
}

function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  return fetch(`${API}${path}`, {
    ...init,
    headers,
    credentials: 'include',
    cache: init.cache ?? 'no-store',
  });
}

// Compute (and commit) the plan for a day. Mirrors run_daily_plan's own
// idempotency: calling this again for the same day reconciles, not duplicates.
export async function planDay(day: string): Promise<PlanResponse> {
  const res = await apiFetch(`/api/plan?day=${day}`, { method: 'POST' });
  return (await checkOk(res, 'Failed to plan day')).json();
}

// Current tasks (with status/scheduled time) for a day's store.
export async function getTasks(day: string): Promise<TaskRow[]> {
  const res = await apiFetch(`/api/tasks?day=${day}`);
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
  const res = await apiFetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to create task')).json();
}

export interface UpdateTaskInput {
  name?: string;
  estDurationMin?: number;
  priority?: string;
  plannedDate?: string | null;
  category?: string;
  status?: string;
  fixedTime?: string | null;
}

export async function updateTask(taskId: string, input: UpdateTaskInput): Promise<TaskRow> {
  const res = await apiFetch(`/api/tasks/${taskId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to update task')).json();
}

export async function deleteTask(taskId: string): Promise<void> {
  const res = await apiFetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete task');
}

export async function getCategoryWeights(): Promise<CategoryWeight[]> {
  const res = await apiFetch('/api/category-weights');
  return (await checkOk(res, 'Failed to load category weights')).json();
}

export async function putCategoryWeights(weights: CategoryWeight[]): Promise<CategoryWeight[]> {
  const res = await apiFetch('/api/category-weights', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(weights),
  });
  return (await checkOk(res, 'Failed to save category weights')).json();
}

export async function applyCategoryWeights(): Promise<{ updated: number }> {
  const res = await apiFetch('/api/category-weights/apply', { method: 'POST' });
  return (await checkOk(res, 'Failed to apply category weights')).json();
}

export async function getUpcomingInterviews(): Promise<Interview[]> {
  const res = await apiFetch('/api/interviews?upcoming=true');
  return (await checkOk(res, 'Failed to load interviews')).json();
}

export interface CreateInterviewInput {
  applicationId: string;
  category: string;
  scheduledAt: string;
  notes?: string;
}

export async function createInterview(input: CreateInterviewInput): Promise<Interview> {
  const res = await apiFetch('/api/interviews', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to create interview')).json();
}

export async function deleteInterview(interviewId: string): Promise<void> {
  const res = await apiFetch(`/api/interviews/${interviewId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete interview');
}

export interface CalendarStatus {
  connected: boolean;
}

export async function getCalendarStatus(): Promise<CalendarStatus> {
  const res = await apiFetch('/api/calendar/status');
  return (await checkOk(res, 'Failed to load calendar status')).json();
}

// Runs the (one-time) Google OAuth flow server-side - on failure, surfaces
// the backend's exact setup-gap message (e.g. missing credentials.json)
// rather than a generic error, since that message tells the user what to do.
export async function connectCalendar(): Promise<CalendarStatus> {
  const res = await apiFetch('/api/calendar/connect', { method: 'POST' });
  if (res.status === 401 || res.status === 403) redirectForAuth(res.status);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? 'Failed to connect Google Calendar');
  }
  return res.json();
}

export async function syncInterviewsToCalendar(): Promise<{ synced: number }> {
  const res = await apiFetch('/api/calendar/sync-interviews', { method: 'POST' });
  if (res.status === 401 || res.status === 403) redirectForAuth(res.status);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? 'Failed to sync interviews');
  }
  return res.json();
}

// Interviews are now auto-discovered from the connected calendar (see
// api/main.py's _reconcile_calendar_interviews, run on every
// getUpcomingInterviews() call) - no manual import step. Category is the one
// field a user still sets by hand on a discovered interview.
export async function updateInterviewCategory(
  interviewId: string,
  category: string
): Promise<Interview> {
  const res = await apiFetch(`/api/interviews/${interviewId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category }),
  });
  return (await checkOk(res, 'Failed to update category')).json();
}

// Dismisses a calendar-discovered interview without touching its real
// calendar event - what the "x" button does for anything Dayline doesn't own.
export async function hideInterview(interviewId: string): Promise<void> {
  await deleteInterview(interviewId);
}

export async function getHiddenInterviews(): Promise<Interview[]> {
  const res = await apiFetch('/api/interviews/hidden');
  return (await checkOk(res, 'Failed to load hidden interviews')).json();
}

export async function unhideInterview(interviewId: string): Promise<Interview> {
  const res = await apiFetch(`/api/interviews/${interviewId}/unhide`, { method: 'POST' });
  return (await checkOk(res, 'Failed to unhide interview')).json();
}

export async function getApplications(): Promise<Application[]> {
  const res = await apiFetch('/api/applications');
  return (await checkOk(res, 'Failed to load applications')).json();
}

export interface CreateApplicationInput {
  company: string;
  role: string;
  stage?: string;
}

export async function createApplication(input: CreateApplicationInput): Promise<Application> {
  const res = await apiFetch('/api/applications', {
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
  const res = await apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day, message, history }),
  });
  return (await checkOk(res, 'Failed to reach chat')).json();
}

export interface ChatStreamHandlers {
  onStatus?: (message: string) => void;
  onDelta?: (text: string) => void;
  onDone?: (res: ChatResponse) => void;
  onError?: (message: string) => void;
}

// Streaming twin of sendChatMessage. Reads the SSE frames the API emits
// (`data: <json>\n\n`) and dispatches them; the terminal `done` frame carries
// the same payload sendChatMessage resolves with.
export async function streamChatMessage(
  day: string,
  message: string,
  history: unknown[] | undefined,
  handlers: ChatStreamHandlers
): Promise<void> {
  const res = await apiFetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day, message, history }),
  });
  if (!res.ok) {
    await checkOk(res, 'Failed to reach chat');
  }
  if (!res.body) throw new Error('Failed to reach chat');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (frame: string): void => {
    const line = frame.split('\n').find((l) => l.startsWith('data:'));
    if (!line) return;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(line.slice(5).trim());
    } catch {
      return; // ignore a frame we can't parse rather than killing the stream
    }
    switch (payload.type) {
      case 'status':
        handlers.onStatus?.(String(payload.message ?? ''));
        break;
      case 'delta':
        handlers.onDelta?.(String(payload.text ?? ''));
        break;
      case 'done':
        handlers.onDone?.(payload as unknown as ChatResponse);
        break;
      case 'error':
        handlers.onError?.(String(payload.message ?? 'Chat stream failed'));
        break;
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split = buffer.indexOf('\n\n');
    while (split !== -1) {
      dispatch(buffer.slice(0, split));
      buffer = buffer.slice(split + 2);
      split = buffer.indexOf('\n\n');
    }
  }
  if (buffer.trim()) dispatch(buffer);
}

export async function confirmProposals(
  day: string,
  proposals: Proposal[],
  offered?: Proposal[]
): Promise<ChatConfirmResponse> {
  const res = await apiFetch('/api/chat/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day, proposals, offered }),
  });
  return (await checkOk(res, 'Failed to apply proposals')).json();
}

export async function getPreferences(): Promise<PlannerPreferences> {
  const res = await apiFetch('/api/preferences');
  return (await checkOk(res, 'Failed to load preferences')).json();
}

export async function putPreferences(
  input: Partial<PlannerPreferences>
): Promise<PlannerPreferences> {
  const res = await apiFetch('/api/preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await checkOk(res, 'Failed to save preferences')).json();
}

export async function getMe(): Promise<AuthUser> {
  const res = await apiFetch('/api/auth/me');
  return (await checkOk(res, 'Sign in required')).json();
}

export async function signOut(): Promise<void> {
  await apiFetch('/api/auth/logout', { method: 'POST' });
  if (typeof window !== 'undefined') {
    window.location.replace('/login');
  }
}
