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
  problemId: string | null;
  mockSessionId: string | null;
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

// An HTTP error with its status, so callers can tell e.g. a save conflict
// (409) from a failure.
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
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
    throw new ApiError(detail || message, res.status);
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
  problemId?: string | null;
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

// ---- Problems (LeetCode tracker) -------------------------------------------

export interface Problem {
  id: string;
  number: number | null;
  slug: string | null;
  title: string;
  url: string | null;
  difficulty: string;
  status: string;
  confidence: number | null;
  notes: string;
  starred: boolean;
  tagIds: string[];
  createdAt: string | null;
  updatedAt: string | null;
  lastAttemptedAt: string | null;
  solvedAt: string | null;
}

export interface Solution {
  id: string;
  problemId: string;
  title: string;
  language: string;
  code: string;
  timeComplexity: string | null;
  spaceComplexity: string | null;
  explanation: string;
  isOptimal: boolean;
  createdAt: string | null;
}

export interface ProblemDetail extends Problem {
  solutions: Solution[];
  // Practice sessions (Leetcode tasks) linked to this problem.
  tasks: TaskRow[];
}

export interface ProblemTag {
  id: string;
  name: string;
  color: string | null;
  problemCount: number;
}

// Every field optional so PATCH can send only what changed; null clears.
export interface ProblemInput {
  title?: string;
  difficulty?: string;
  status?: string;
  number?: number | null;
  slug?: string | null;
  url?: string | null;
  confidence?: number | null;
  notes?: string;
  starred?: boolean;
  tagIds?: string[];
}

export interface SolutionInput {
  title: string;
  language: string;
  code: string;
  timeComplexity: string | null;
  spaceComplexity: string | null;
  explanation: string;
  isOptimal: boolean;
}

export interface ProblemTagInput {
  name: string;
  color: string | null;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

export async function getProblems(): Promise<Problem[]> {
  const res = await apiFetch('/api/problems');
  return (await checkOk(res, 'Failed to load problems')).json();
}

export async function getProblem(problemId: string): Promise<ProblemDetail> {
  const res = await apiFetch(`/api/problems/${problemId}`);
  return (await checkOk(res, 'Failed to load problem')).json();
}

export async function createProblem(input: ProblemInput): Promise<Problem> {
  const res = await apiFetch('/api/problems', jsonInit('POST', input));
  return (await checkOk(res, 'Failed to create problem')).json();
}

export async function updateProblem(problemId: string, input: ProblemInput): Promise<Problem> {
  const res = await apiFetch(`/api/problems/${problemId}`, jsonInit('PATCH', input));
  return (await checkOk(res, 'Failed to update problem')).json();
}

export async function deleteProblem(problemId: string): Promise<void> {
  const res = await apiFetch(`/api/problems/${problemId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete problem');
}

export async function exportProblems(): Promise<unknown> {
  const res = await apiFetch('/api/problems/export');
  return (await checkOk(res, 'Failed to export problems')).json();
}

export async function createSolution(problemId: string, input: SolutionInput): Promise<Solution> {
  const res = await apiFetch(`/api/problems/${problemId}/solutions`, jsonInit('POST', input));
  return (await checkOk(res, 'Failed to add solution')).json();
}

export async function updateSolution(solutionId: string, input: SolutionInput): Promise<Solution> {
  const res = await apiFetch(`/api/solutions/${solutionId}`, jsonInit('PUT', input));
  return (await checkOk(res, 'Failed to save solution')).json();
}

export async function deleteSolution(solutionId: string): Promise<void> {
  const res = await apiFetch(`/api/solutions/${solutionId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete solution');
}

export async function getProblemTags(): Promise<ProblemTag[]> {
  const res = await apiFetch('/api/problem-tags');
  return (await checkOk(res, 'Failed to load tags')).json();
}

export async function createProblemTag(input: ProblemTagInput): Promise<ProblemTag> {
  const res = await apiFetch('/api/problem-tags', jsonInit('POST', input));
  return (await checkOk(res, 'Failed to create tag')).json();
}

export async function updateProblemTag(tagId: string, input: ProblemTagInput): Promise<ProblemTag> {
  const res = await apiFetch(`/api/problem-tags/${tagId}`, jsonInit('PUT', input));
  return (await checkOk(res, 'Failed to save tag')).json();
}

export async function deleteProblemTag(tagId: string): Promise<void> {
  const res = await apiFetch(`/api/problem-tags/${tagId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete tag');
}

// ---------------------------------------------------------------------------
// Mock interviews (the Mock tab). Mirrors dayline.api.serializers mock_*_json.
// ---------------------------------------------------------------------------

export interface MockQuestion {
  id: string;
  source: string;
  sourceUrl: string | null;
  company: string | null;
  role: string | null;
  roundType: string;
  title: string;
  promptMd: string;
  constraints: string[];
  followUps: string[];
  languageHint: string | null;
  originalText: string;
  originalLanguage: string | null;
  reportedOn: string | null;
  canonicalId: string | null;
  notes: string;
  timesSeen: number;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface MockSessionSummary {
  id: string;
  title: string;
  questionId: string | null;
  rubricId: string | null;
  guidelineId: string | null;
  kind: 'transcript' | 'live';
  status: 'live' | 'ended';
  templateId: string | null;
  pack: string | null;
  startedAt: string | null;
  endedAt: string | null;
  overallScore: number | null;
  // Staged rounds only (null otherwise).
  stagedProblemId: string | null;
  stageCount: number | null;
  stagesPassed: number | null;
  createdAt: string | null;
}

export interface MockQuestionDetail extends MockQuestion {
  copies: MockQuestion[];
  sessions: MockSessionSummary[];
}

// Every field optional so PATCH can send just what changed.
export type MockQuestionInput = Partial<
  Omit<MockQuestion, 'id' | 'timesSeen' | 'createdAt' | 'updatedAt'>
>;

export interface SimilarQuestion {
  id: string;
  title: string;
  company: string | null;
  score: number;
}

export interface ExtractedQuestion {
  title: string;
  roundType: string;
  promptMd: string;
  company: string | null;
  role: string | null;
  constraints: string[];
  followUps: string[];
  languageHint: string | null;
  reportedOn: string | null;
  similar: SimilarQuestion[];
}

export interface Extraction {
  originalLanguage: string | null;
  questions: ExtractedQuestion[];
}

export interface RubricCriterion {
  key: string;
  title: string;
  description: string;
  weight: number;
}

export interface MockRubric {
  id: string;
  name: string;
  roundType: string | null;
  criteria: RubricCriterion[];
  updatedAt: string | null;
}

export interface MockRubricInput {
  name: string;
  roundType: string | null;
  // key is optional on new criteria: the server derives it from the title.
  criteria: (Omit<RubricCriterion, 'key'> & { key?: string })[];
}

export interface MockGuideline {
  id: string;
  name: string;
  bodyMd: string;
  updatedAt: string | null;
}

export interface Evidence {
  quote: string;
  // True only when the quote really appears in the transcript (checked in code).
  verified: boolean;
}

export interface CriterionScore {
  key: string;
  title: string;
  score: number;
  evidence: Evidence[];
  improvement: string;
}

export interface WeakArea {
  title: string;
  why: string;
  taskName: string;
  category: string;
  estDurationMin: number;
}

export interface Scorecard {
  id: string;
  sessionId: string;
  overallScore: number;
  summary: string;
  criteria: CriterionScore[];
  strengths: string[];
  weakAreas: WeakArea[];
  graderModel: string;
  createdAt: string | null;
}

export interface MockSessionDetail extends MockSessionSummary {
  transcript: string;
  scorecard: Scorecard | null;
  // The scorecard's weak areas as propose_new_task proposals for confirmProposals.
  proposals: Proposal[];
  tasks: TaskRow[];
  // Live sessions only.
  templateTitle?: string | null;
  taskMd?: string;
  durationMin?: number | null;
  // The file the workspace opens first.
  openPath?: string | null;
  testReport?: TestReport | null;
  finalDiff?: string;
  events?: MockEvent[];
  // Staged rounds only.
  staged?: StagedRound | null;
}

// Live sessions (a sandbox per session). Mirrors services/mock_live.py and
// the sandbox runner's JSON.
export interface LiveTemplate {
  id: string;
  title: string;
  pack: string;
  roundType: string;
  durationMin: number;
  summary: string;
}

export interface LivePack {
  name: string;
  displayName: string;
  editorLanguage: string;
  state: 'pending' | 'building' | 'ready' | 'failed';
  error: string | null;
}

export interface StagedProblemSummary {
  id: string;
  title: string;
  pack: string;
  roundType: string;
  durationMin: number;
  summary: string;
  stageCount: number;
}

export interface LiveAvailability {
  available: boolean;
  reason: string | null;
  templates: LiveTemplate[];
  stagedProblems: StagedProblemSummary[];
  packs: LivePack[];
}

export interface LiveSessionInput {
  templateId: string;
  questionId: string | null;
  rubricId: string | null;
  guidelineId: string | null;
}

export interface SandboxStatus {
  // stopped: idle too long or out of time (files kept); gone: deleted.
  state: 'running' | 'stopped' | 'gone';
  expiresAt?: string;
  idleTimeoutS?: number;
  editorLanguage: string | null;
}

export interface WorkspaceFile {
  path: string;
  size: number;
  version: string;
}

export interface FileContent {
  path: string;
  content: string;
  version: string;
}

export interface TestCase {
  name: string;
  classname: string;
  outcome: 'passed' | 'failed' | 'error' | 'skipped';
  message: string;
  duration_s: number;
}

export interface TestReport {
  // error: the tests could not run at all; timeout: stopped at the limit.
  status: 'passed' | 'failed' | 'error' | 'timeout';
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_s: number;
  exit_code: number | null;
  output: string;
  cases: TestCase[];
}

export interface MockEvent {
  kind:
    | 'session_started'
    | 'file_saved'
    | 'tests_run'
    | 'command_run'
    | 'session_ended'
    | 'stage_tests_run'
    | 'stage_passed'
    | 'stage_skipped'
    | 'interviewer_message'
    | 'candidate_message';
  data: Record<string, unknown>;
  at: string | null;
}

// Staged rounds. Mirrors serializers.staged_round_json and mock/staged.py.
export type StageStatus = 'locked' | 'active' | 'passed' | 'skipped' | 'failed';

// hit: handled before the tests said anything; caught: fixed after a failing
// run; pending: the stage is still active.
export type EdgeOutcome = 'hit' | 'caught' | 'missed' | 'pending' | 'not_reached';

export interface StagedStage {
  number: number;
  // null while the stage is locked.
  title: string | null;
  promptMd: string | null;
  targetMin: number | null;
  status: StageStatus;
  startedAt: string | null;
  finishedAt: string | null;
  timeSpentS: number | null;
  runs: number;
  report: TestReport | null;
  // How much of the previous stage's code survived (null for stage 1).
  design: { kept: number; verdict: 'extended' | 'rewrote' } | null;
  // Empty until the stage (or the round) is over.
  edgeCases: { id: string; title: string; outcome: EdgeOutcome }[];
}

export interface ChatMessage {
  role: 'interviewer' | 'candidate';
  text: string;
  stage: number;
  at: string | null;
}

export interface StagedRound {
  problemId: string;
  // 1-based; null once every stage is done.
  activeStage: number | null;
  stages: StagedStage[];
  chat: ChatMessage[];
}

export interface StageRun {
  report: TestReport;
  passed: boolean;
  staged: StagedRound;
}

export type InterviewerTrigger = 'stage_start' | 'follow_up' | 'message';

export interface MockSessionInput {
  title: string;
  transcript: string;
  questionId: string | null;
  rubricId: string | null;
  guidelineId: string | null;
}

export async function getMockQuestions(): Promise<MockQuestion[]> {
  const res = await apiFetch('/api/mock/questions');
  return (await checkOk(res, 'Failed to load questions')).json();
}

export async function getMockQuestion(questionId: string): Promise<MockQuestionDetail> {
  const res = await apiFetch(`/api/mock/questions/${questionId}`);
  return (await checkOk(res, 'Failed to load question')).json();
}

export async function createMockQuestion(input: MockQuestionInput): Promise<MockQuestion> {
  const res = await apiFetch('/api/mock/questions', jsonInit('POST', input));
  return (await checkOk(res, 'Failed to save question')).json();
}

export async function updateMockQuestion(
  questionId: string,
  input: MockQuestionInput
): Promise<MockQuestion> {
  const res = await apiFetch(`/api/mock/questions/${questionId}`, jsonInit('PATCH', input));
  return (await checkOk(res, 'Failed to save question')).json();
}

export async function deleteMockQuestion(questionId: string): Promise<void> {
  const res = await apiFetch(`/api/mock/questions/${questionId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete question');
}

export async function extractMockQuestions(text: string): Promise<Extraction> {
  const res = await apiFetch('/api/mock/extract', jsonInit('POST', { text }));
  return (await checkOk(res, 'Failed to extract questions')).json();
}

export async function getMockRubrics(): Promise<MockRubric[]> {
  const res = await apiFetch('/api/mock/rubrics');
  return (await checkOk(res, 'Failed to load rubrics')).json();
}

export async function createMockRubric(input: MockRubricInput): Promise<MockRubric> {
  const res = await apiFetch('/api/mock/rubrics', jsonInit('POST', input));
  return (await checkOk(res, 'Failed to save rubric')).json();
}

export async function updateMockRubric(rubricId: string, input: MockRubricInput): Promise<MockRubric> {
  const res = await apiFetch(`/api/mock/rubrics/${rubricId}`, jsonInit('PUT', input));
  return (await checkOk(res, 'Failed to save rubric')).json();
}

export async function deleteMockRubric(rubricId: string): Promise<void> {
  const res = await apiFetch(`/api/mock/rubrics/${rubricId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete rubric');
}

export async function getMockGuidelines(): Promise<MockGuideline[]> {
  const res = await apiFetch('/api/mock/guidelines');
  return (await checkOk(res, 'Failed to load guidelines')).json();
}

export async function createMockGuideline(input: {
  name: string;
  bodyMd: string;
}): Promise<MockGuideline> {
  const res = await apiFetch('/api/mock/guidelines', jsonInit('POST', input));
  return (await checkOk(res, 'Failed to save guideline')).json();
}

export async function updateMockGuideline(
  guidelineId: string,
  input: { name: string; bodyMd: string }
): Promise<MockGuideline> {
  const res = await apiFetch(`/api/mock/guidelines/${guidelineId}`, jsonInit('PUT', input));
  return (await checkOk(res, 'Failed to save guideline')).json();
}

export async function deleteMockGuideline(guidelineId: string): Promise<void> {
  const res = await apiFetch(`/api/mock/guidelines/${guidelineId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete guideline');
}

export async function getMockSessions(): Promise<MockSessionSummary[]> {
  const res = await apiFetch('/api/mock/sessions');
  return (await checkOk(res, 'Failed to load sessions')).json();
}

export async function getMockSession(sessionId: string): Promise<MockSessionDetail> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}`);
  return (await checkOk(res, 'Failed to load session')).json();
}

export async function createMockSession(input: MockSessionInput): Promise<MockSessionDetail> {
  const res = await apiFetch('/api/mock/sessions', jsonInit('POST', input));
  return (await checkOk(res, 'Failed to save session')).json();
}

export async function gradeMockSession(sessionId: string): Promise<MockSessionDetail> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/grade`, { method: 'POST' });
  return (await checkOk(res, 'Grading failed')).json();
}

export async function deleteMockSession(sessionId: string): Promise<void> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}`, { method: 'DELETE' });
  await checkOk(res, 'Failed to delete session');
}

export async function getLiveAvailability(): Promise<LiveAvailability> {
  const res = await apiFetch('/api/mock/live');
  return (await checkOk(res, 'Failed to load practice repos')).json();
}

export async function startLiveSession(input: LiveSessionInput): Promise<MockSessionDetail> {
  const res = await apiFetch('/api/mock/live/sessions', jsonInit('POST', input));
  return (await checkOk(res, 'Could not start the session')).json();
}

export async function startStagedRound(input: {
  problemId: string;
  questionId: string | null;
  rubricId: string | null;
  guidelineId: string | null;
}): Promise<MockSessionDetail> {
  const res = await apiFetch('/api/mock/staged/sessions', jsonInit('POST', input));
  return (await checkOk(res, 'Could not start the round')).json();
}

// Runs the active stage's hidden tests; a pass unlocks the next stage.
export async function runStageTests(sessionId: string): Promise<StageRun> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/stage/tests`, { method: 'POST' });
  return (await checkOk(res, 'Could not run the tests')).json();
}

export async function skipStage(sessionId: string): Promise<StagedRound> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/stage/skip`, { method: 'POST' });
  return (await checkOk(res, 'Could not skip the stage')).json();
}

export async function interviewerTurn(
  sessionId: string,
  trigger: InterviewerTrigger,
  message?: string,
): Promise<StagedRound> {
  const res = await apiFetch(
    `/api/mock/sessions/${sessionId}/interviewer`,
    jsonInit('POST', { trigger, message: message ?? null }),
  );
  return (await checkOk(res, 'The interviewer could not reply')).json();
}

export async function getSandboxStatus(sessionId: string): Promise<SandboxStatus> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/sandbox`);
  return (await checkOk(res, 'Failed to load the sandbox')).json();
}

export async function resumeSandbox(sessionId: string): Promise<SandboxStatus> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/resume`, { method: 'POST' });
  return (await checkOk(res, 'Could not resume the sandbox')).json();
}

function filePath(sessionId: string, path: string): string {
  return `/api/mock/sessions/${sessionId}/files/${path.split('/').map(encodeURIComponent).join('/')}`;
}

export async function listWorkspaceFiles(sessionId: string): Promise<WorkspaceFile[]> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/files`);
  return (await checkOk(res, 'Failed to list files')).json();
}

export async function readWorkspaceFile(sessionId: string, path: string): Promise<FileContent> {
  const res = await apiFetch(filePath(sessionId, path));
  return (await checkOk(res, `Could not open ${path}`)).json();
}

// baseVersion: the version the editor loaded ('' for a new file). A file that
// changed since then fails with ApiError status 409.
export async function writeWorkspaceFile(
  sessionId: string,
  path: string,
  content: string,
  baseVersion: string | null,
): Promise<{ path: string; version: string }> {
  const res = await apiFetch(filePath(sessionId, path), jsonInit('PUT', { content, baseVersion }));
  return (await checkOk(res, `Could not save ${path}`)).json();
}

export async function runWorkspaceTests(sessionId: string): Promise<TestReport> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/tests`, { method: 'POST' });
  return (await checkOk(res, 'Could not run the tests')).json();
}

export async function endLiveSession(sessionId: string): Promise<MockSessionDetail> {
  const res = await apiFetch(`/api/mock/sessions/${sessionId}/end`, { method: 'POST' });
  return (await checkOk(res, 'Could not end the session')).json();
}

// The terminal WebSocket. Same origin as the API (the Next dev server and
// Caddy both proxy /api, upgrades included).
export function terminalUrl(sessionId: string, cols: number, rows: number): string {
  const base = API || window.location.origin;
  const url = new URL(`/api/mock/sessions/${sessionId}/terminal`, base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.search = `cols=${cols}&rows=${rows}`;
  return url.toString();
}
