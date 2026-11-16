'use client';

import CodeMirror from '@uiw/react-codemirror';
import { Prec } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  GeneratedPreviewStatus,
  GeneratedProject,
  InterviewerStyle,
  MockGuideline,
  MockRubric,
  cancelGeneratedProject,
  deleteGeneratedProject,
  generatedPreviewApi,
  getGeneratedPreview,
  getGeneratedProject,
  getMockGuidelines,
  getMockRubrics,
  regenerateProject,
  startGeneratedPreview,
  startGeneratedRound,
  stopGeneratedPreview,
} from '../../lib/api';
import { MAX_REPAIRS, PHASES, formatBytes, phaseIndex, stackLabel } from '../../lib/generated';
import { buildFileTree, formatClock, languageForPath } from '../../lib/mock';
import { useIsDark } from '../../lib/useIsDark';
import { languageExtensions } from '../problems/CodeEditor';
import { MarkdownView } from '../problems/Markdown';
import { FileTree } from './FileTree';
import { PreviewPane } from './PreviewPane';
import {
  BackButton,
  CARD,
  DANGER_BUTTON,
  ErrorText,
  FIELD,
  Label,
  Pill,
  PRIMARY_BUTTON,
  QUIET_BUTTON,
  SECONDARY_BUTTON,
  SECTION_TITLE,
} from './ui';

// The long poll answers within this many seconds even when nothing moved.
const WAIT_S = 20;
// When the worker runs in another server process there is no long poll.
const POLL_MS = 2500;
const RETRY_MS = 3000;

const viewerTheme = Prec.highest(
  EditorView.theme({
    '&': { height: '100%', backgroundColor: 'var(--editor-bg)', fontSize: '0.8rem' },
    '&.cm-focused': { outline: 'none' },
    '.cm-scroller': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' },
    '.cm-gutters': { backgroundColor: 'var(--editor-bg)', border: 'none' },
  }),
);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function message(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

interface Props {
  projectId: string;
  onBack: () => void;
  // Regenerating makes a new project; open that one.
  onOpenProject: (projectId: string) => void;
  onStarted: (sessionId: string) => void;
}

// One generated project: its live progress while it generates, why it
// failed if it did, and once ready a look at it before starting the round:
// the task, the change request (hidden until revealed), the code, and the
// running app.
export function GeneratedProjectView({ projectId, onBack, onOpenProject, onStarted }: Props) {
  const [project, setProject] = useState<GeneratedProject | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Follow the project until it stops generating.
  useEffect(() => {
    let stopped = false;
    const abort = new AbortController();
    (async () => {
      let current: GeneratedProject | null = null;
      while (!stopped) {
        try {
          if (current == null) {
            current = await getGeneratedProject(projectId, undefined, abort.signal);
          } else if (current.version != null) {
            current = await getGeneratedProject(
              projectId,
              { version: current.version, waitS: WAIT_S },
              abort.signal,
            );
          } else {
            await sleep(POLL_MS);
            if (stopped) return;
            current = await getGeneratedProject(projectId, undefined, abort.signal);
          }
          if (stopped) return;
          setProject(current);
          setLoadError(null);
          if (current.status !== 'generating') return;
        } catch (err) {
          if (stopped) return;
          setLoadError(message(err, 'Could not load the project.'));
          await sleep(RETRY_MS);
        }
      }
    })();
    return () => {
      stopped = true;
      abort.abort();
    };
  }, [projectId]);

  if (!project) {
    return (
      <div className="flex flex-col gap-3 max-w-3xl">
        <BackButton onClick={onBack}>Practice</BackButton>
        {loadError ? <ErrorText>{loadError}</ErrorText> : <p className="font-mono text-sm text-zinc-500">Loading…</p>}
      </div>
    );
  }
  if (project.status === 'generating') {
    return <Generating project={project} onBack={onBack} onChange={setProject} />;
  }
  if (project.status === 'ready' && project.project) {
    return (
      <Ready project={project} onBack={onBack} onOpenProject={onOpenProject} onStarted={onStarted} />
    );
  }
  return <Failed project={project} onBack={onBack} onOpenProject={onOpenProject} />;
}

function RequestSummary({ project }: { project: GeneratedProject }) {
  return (
    <div className={`${CARD} p-4 flex flex-col gap-2`}>
      <p className={SECTION_TITLE}>YOUR ROUND</p>
      <p className="text-sm text-zinc-800 dark:text-zinc-200 whitespace-pre-wrap break-words">{project.prompt}</p>
      <div className="flex items-center gap-2 flex-wrap">
        <Pill>{stackLabel(project.stack)}</Pill>
        <Pill className="capitalize">{project.difficulty}</Pill>
        <Pill>{project.durationMin} min</Pill>
        <Pill>Change request at {project.changeRequestMin} min</Pill>
        {project.contextFiles.length > 0 && (
          <Pill title={project.contextFiles.map((f) => `${f.name} (${formatBytes(f.bytes)})`).join('\n')}>
            {project.contextFiles.length} context {project.contextFiles.length === 1 ? 'file' : 'files'}
          </Pill>
        )}
      </div>
      {project.feedback && (
        <p className="text-sm text-zinc-500">
          <span className="text-zinc-700 dark:text-zinc-300">Feedback:</span> {project.feedback}
        </p>
      )}
    </div>
  );
}

// -- generating ----------------------------------------------------------------------

function Generating({
  project,
  onBack,
  onChange,
}: {
  project: GeneratedProject;
  onBack: () => void;
  onChange: (project: GeneratedProject) => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const current = phaseIndex(project.progress);
  const attempt = project.progress.attempt ?? 0;
  const started = project.createdAt ? Date.parse(project.createdAt) : now;

  async function cancel() {
    setCancelling(true);
    setError(null);
    try {
      onChange(await cancelGeneratedProject(project.id));
    } catch (err) {
      setError(message(err, 'Could not cancel.'));
      setCancelling(false);
    }
  }

  return (
    <div className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onBack}>Practice</BackButton>
        <h2 className="text-lg font-semibold">Generating your round</h2>
      </div>

      <div className={`${CARD} p-5 flex flex-col gap-4`} aria-live="polite">
        <div className="flex items-center gap-3 flex-wrap">
          <p className="text-sm text-zinc-500">
            Usually 2 to 5 minutes. You can leave this page: it keeps going and shows under Practice.
          </p>
          <span className="ml-auto font-mono text-sm tabular-nums text-zinc-500">
            {formatClock(Math.max(0, Math.floor((now - started) / 1000)))}
          </span>
        </div>
        <ol className="flex flex-col gap-3">
          {PHASES.map((phase, i) => {
            const state = i < current ? 'done' : i === current ? 'active' : 'pending';
            return (
              <li key={phase.id} className="flex items-start gap-3">
                <StepIcon state={state} />
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-sm ${
                      state === 'pending'
                        ? 'text-zinc-400 dark:text-zinc-500'
                        : 'text-zinc-900 dark:text-zinc-100 font-medium'
                    }`}
                  >
                    {phase.label}
                    {state === 'active' && attempt > 0 && (
                      <Pill className="ml-2 align-middle !bg-amber-100 !text-amber-800 dark:!bg-amber-500/15 dark:!text-amber-300">
                        repair {attempt}/{MAX_REPAIRS}
                      </Pill>
                    )}
                  </p>
                  {state === 'active' && project.progress.detail && (
                    <p className="mt-0.5 font-mono text-xs text-zinc-500 break-words">{project.progress.detail}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {attempt > 0 && (
          <p className="text-sm text-zinc-500">
            The last attempt did not pass every check, so the problems went back to the model to fix (up to{' '}
            {MAX_REPAIRS} times).
          </p>
        )}
        {error && <ErrorText>{error}</ErrorText>}
        <div>
          <button onClick={() => void cancel()} disabled={cancelling} className={SECONDARY_BUTTON}>
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        </div>
      </div>

      <RequestSummary project={project} />
    </div>
  );
}

function StepIcon({ state }: { state: 'done' | 'active' | 'pending' }) {
  if (state === 'active') {
    return (
      <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 border-zinc-300 dark:border-zinc-700 border-t-indigo-500 dark:border-t-indigo-400 animate-spin" />
    );
  }
  if (state === 'done') {
    return (
      <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full bg-emerald-500 text-white flex items-center justify-center">
        <svg viewBox="0 0 16 16" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3.5 8.5l3 3 6-7" />
        </svg>
      </span>
    );
  }
  return <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 border-zinc-200 dark:border-zinc-800" />;
}

// -- regenerate / delete ------------------------------------------------------------

function useProjectActions(projectId: string, onOpenProject: (id: string) => void, onBack: () => void) {
  const [busy, setBusy] = useState<'regenerate' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function regenerate(feedback: string) {
    setBusy('regenerate');
    setError(null);
    try {
      onOpenProject((await regenerateProject(projectId, feedback)).id);
    } catch (err) {
      setError(message(err, 'Could not regenerate.'));
      setBusy(null);
    }
  }

  async function remove() {
    setBusy('delete');
    setError(null);
    try {
      await deleteGeneratedProject(projectId);
      onBack();
    } catch (err) {
      setError(message(err, 'Could not delete the project.'));
      setBusy(null);
    }
  }

  return { busy, error, regenerate, remove };
}

function RegeneratePanel({
  busy,
  onRegenerate,
  onClose,
}: {
  busy: boolean;
  onRegenerate: (feedback: string) => void;
  onClose?: () => void;
}) {
  const [feedback, setFeedback] = useState('');
  return (
    <div className={`${CARD} p-4 flex flex-col gap-3`}>
      <div>
        <Label htmlFor="g-feedback">What should be different? (optional)</Label>
        <textarea
          id="g-feedback"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder="e.g. Make the task harder, and keep the API smaller."
          className={`${FIELD} resize-y`}
        />
      </div>
      <div className="flex items-center gap-2">
        <button onClick={() => onRegenerate(feedback)} disabled={busy} className={PRIMARY_BUTTON}>
          {busy ? 'Starting…' : 'Regenerate'}
        </button>
        {onClose && (
          <button onClick={onClose} className={QUIET_BUTTON}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

function DeleteButton({ busy, onDelete }: { busy: boolean; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return (
      <button onClick={() => setConfirming(true)} className={DANGER_BUTTON}>
        Delete
      </button>
    );
  }
  return (
    <span className="flex items-center gap-1">
      <span className="text-sm text-zinc-500 whitespace-nowrap">Delete it?</span>
      <button onClick={onDelete} disabled={busy} className={`${DANGER_BUTTON} !text-rose-600 dark:!text-rose-400`}>
        {busy ? 'Deleting…' : 'Delete'}
      </button>
      <button onClick={() => setConfirming(false)} className={QUIET_BUTTON}>
        Keep
      </button>
    </span>
  );
}

// -- failed or cancelled ------------------------------------------------------------

function Failed({
  project,
  onBack,
  onOpenProject,
}: {
  project: GeneratedProject;
  onBack: () => void;
  onOpenProject: (id: string) => void;
}) {
  const actions = useProjectActions(project.id, onOpenProject, onBack);
  const cancelled = project.status === 'cancelled';
  return (
    <div className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onBack}>Practice</BackButton>
        <h2 className="text-lg font-semibold">{cancelled ? 'Generation cancelled' : 'Generation failed'}</h2>
        <span className="ml-auto">
          <DeleteButton busy={actions.busy === 'delete'} onDelete={() => void actions.remove()} />
        </span>
      </div>
      {!cancelled && (
        <div className="rounded-lg border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-950/20 px-4 py-3">
          <p className="text-sm text-rose-700 dark:text-rose-300 break-words">{project.error}</p>
          <p className="mt-1 text-sm text-zinc-500">
            Nothing unchecked is handed over. Try again, perhaps with a smaller or clearer round.
          </p>
        </div>
      )}
      <RequestSummary project={project} />
      <RegeneratePanel busy={actions.busy === 'regenerate'} onRegenerate={(f) => void actions.regenerate(f)} />
      {actions.error && <ErrorText>{actions.error}</ErrorText>}
      {project.log.length > 0 && <AttemptLog project={project} />}
    </div>
  );
}

function AttemptLog({ project }: { project: GeneratedProject }) {
  return (
    <details className={`${CARD} group`}>
      <summary className="cursor-pointer select-none px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
        <svg viewBox="0 0 16 16" className="h-3 w-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 4l4 4-4 4" />
        </svg>
        Attempt log ({project.log.length})
        {project.usage.calls != null && (
          <span className="ml-auto font-mono text-xs text-zinc-500">
            {project.usage.calls} model {project.usage.calls === 1 ? 'call' : 'calls'}
          </span>
        )}
      </summary>
      <ol className="border-t border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-200 dark:divide-zinc-800">
        {project.log.map((entry, i) => (
          <li key={i} className="px-4 py-3 flex flex-col gap-1.5">
            <p className="font-mono text-xs text-zinc-500">
              {entry.attempt === 0 ? 'First draft' : `Repair ${entry.attempt}`} · {entry.kind}
            </p>
            <pre className="max-h-64 overflow-auto rounded-md bg-zinc-50 dark:bg-zinc-950 p-2 font-mono text-[11px] leading-relaxed text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words">
              {entry.message}
            </pre>
          </li>
        ))}
      </ol>
    </details>
  );
}

// The rubric seeded for analysing these rounds (supabase/migrations/016).
const FULL_STACK_RUBRIC = 'AI-assisted full-stack round';

// -- ready: look before you start ---------------------------------------------------

function Ready({
  project,
  onBack,
  onOpenProject,
  onStarted,
}: {
  project: GeneratedProject;
  onBack: () => void;
  onOpenProject: (id: string) => void;
  onStarted: (sessionId: string) => void;
}) {
  const shown = project.project!;
  const actions = useProjectActions(project.id, onOpenProject, onBack);
  const [regenerating, setRegenerating] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [rubrics, setRubrics] = useState<MockRubric[]>([]);
  const [guidelines, setGuidelines] = useState<MockGuideline[]>([]);
  const [rubricId, setRubricId] = useState('');
  const [guidelineId, setGuidelineId] = useState('');
  const [style, setStyle] = useState<InterviewerStyle>('realistic');
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getMockRubrics(), getMockGuidelines()]).then(([rs, gs]) => {
      setRubrics(rs);
      setGuidelines(gs);
      // The analysis rubric (migration 016) when it exists, else any AI-assisted one.
      const preferred =
        rs.find((r) => r.name === FULL_STACK_RUBRIC) ?? rs.find((r) => r.roundType === 'AI-assisted project');
      setRubricId((preferred ?? rs[0])?.id ?? '');
      setGuidelineId(gs[0]?.id ?? '');
    }, () => undefined);
  }, []);

  async function start() {
    setStarting(true);
    setStartError(null);
    try {
      const session = await startGeneratedRound(project.id, {
        questionId: null,
        rubricId: rubricId || null,
        guidelineId: guidelineId || null,
        interviewerStyle: style,
      });
      onStarted(session.id);
    } catch (err) {
      setStartError(message(err, 'Could not start the round.'));
      setStarting(false);
    }
  }

  const outputK = project.usage.outputTokens ? `${(project.usage.outputTokens / 1000).toFixed(1)}k` : null;

  return (
    <div className="flex flex-col gap-5 max-w-6xl">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <BackButton onClick={onBack}>Practice</BackButton>
          <span className="ml-auto flex items-center gap-1">
            <button onClick={() => setRegenerating((v) => !v)} className={QUIET_BUTTON}>
              Regenerate
            </button>
            <DeleteButton busy={actions.busy === 'delete'} onDelete={() => void actions.remove()} />
          </span>
        </div>
        <h2 className="text-lg font-semibold">{project.title}</h2>
        {project.summary && <p className="text-sm text-zinc-500">{project.summary}</p>}
        <div className="flex items-center gap-2 flex-wrap">
          <Pill>{stackLabel(project.stack)}</Pill>
          <Pill className="capitalize">{project.difficulty}</Pill>
          <Pill>AI-assisted · {project.durationMin} min</Pill>
          <Pill>Change request at {shown.changeRequest.atMin} min</Pill>
        </div>
      </div>

      {regenerating && (
        <RegeneratePanel
          busy={actions.busy === 'regenerate'}
          onRegenerate={(f) => void actions.regenerate(f)}
          onClose={() => setRegenerating(false)}
        />
      )}
      {actions.error && <ErrorText>{actions.error}</ErrorText>}

      <div className={`${CARD} p-4 flex flex-col gap-3`}>
        <div className="flex flex-col sm:flex-row sm:items-end gap-3">
          <div className="sm:w-56">
            <Label htmlFor="g-rubric">Rubric</Label>
            <select id="g-rubric" value={rubricId} onChange={(e) => setRubricId(e.target.value)} className={FIELD}>
              <option value="">None (grade later)</option>
              {rubrics.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:w-56">
            <Label htmlFor="g-guideline">Standards</Label>
            <select
              id="g-guideline"
              value={guidelineId}
              onChange={(e) => setGuidelineId(e.target.value)}
              className={FIELD}
            >
              <option value="">None</option>
              {guidelines.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:w-44">
            <Label htmlFor="g-style">Interviewer</Label>
            <select
              id="g-style"
              value={style}
              onChange={(e) => setStyle(e.target.value as InterviewerStyle)}
              className={FIELD}
            >
              <option value="realistic">Realistic</option>
              <option value="coach">Coach</option>
            </select>
          </div>
          <button onClick={() => void start()} disabled={starting} className={`${PRIMARY_BUTTON} sm:ml-auto whitespace-nowrap`}>
            {starting ? 'Starting the sandbox…' : 'Start round'}
          </button>
        </div>
        <p className="text-xs text-zinc-500">
          Starts a timed AI-assisted session in this project with the coding assistant and the app preview. The
          clock starts when you do.{' '}
          {style === 'realistic'
            ? 'A realistic interviewer stays quiet while you code, never says whether you are right, and saves feedback for the end.'
            : 'A coach probes your code and asks follow-ups whenever you want one.'}
        </p>
        {startError && <ErrorText>{startError}</ErrorText>}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className={`${CARD} p-4 flex flex-col gap-2 min-w-0`}>
          <div className="flex items-center gap-2">
            <p className={`${SECTION_TITLE} !mb-0`}>THE TASK</p>
            <span className="ml-auto font-mono text-xs text-zinc-500">about {shown.task.targetMin} min</span>
          </div>
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{shown.task.title}</h3>
          <MarkdownView>{shown.task.promptMd}</MarkdownView>
        </section>
        <section className={`${CARD} p-4 flex flex-col gap-2 min-w-0`}>
          <div className="flex items-center gap-2">
            <p className={`${SECTION_TITLE} !mb-0`}>CHANGE REQUEST · MINUTE {shown.changeRequest.atMin}</p>
            {revealed && (
              <button onClick={() => setRevealed(false)} className="ml-auto text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
                Hide
              </button>
            )}
          </div>
          {revealed ? (
            <>
              <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{shown.changeRequest.title}</h3>
              <MarkdownView>{shown.changeRequest.promptMd}</MarkdownView>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-start justify-center gap-2 rounded-md border border-dashed border-zinc-300 dark:border-zinc-700 px-4 py-6">
              <p className="text-sm text-zinc-700 dark:text-zinc-300">Hidden, like in the real round.</p>
              <p className="text-sm text-zinc-500">
                The interviewer brings it in partway through. Reveal it only if you want to check it.
              </p>
              <button onClick={() => setRevealed(true)} className={`${SECONDARY_BUTTON} mt-1`}>
                Reveal the change request
              </button>
            </div>
          )}
        </section>
      </div>

      <CodeBrowser files={shown.files} openPath={shown.openPath} />

      <AppPreview projectId={project.id} />

      <p className="text-xs text-zinc-500">
        Checked in a sandbox: the app boots, its tests pass, and the hidden tests fail before and pass after each
        reference solution.
        {outputK && ` Generated with ${outputK} output tokens over ${project.usage.calls ?? 1} model ${(project.usage.calls ?? 1) === 1 ? 'call' : 'calls'}.`}
      </p>
    </div>
  );
}

function CodeBrowser({ files, openPath }: { files: Record<string, string>; openPath: string }) {
  const paths = useMemo(() => Object.keys(files).sort(), [files]);
  const tree = useMemo(() => buildFileTree(paths), [paths]);
  const [path, setPath] = useState(files[openPath] != null ? openPath : paths[0]);
  const isDark = useIsDark();
  const extensions = useMemo(
    () => [...languageExtensions(languageForPath(path ?? '')), viewerTheme, EditorView.editable.of(false)],
    [path],
  );
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <p className={`${SECTION_TITLE} !mb-0`}>THE CODE</p>
        <span className="text-xs text-zinc-500">
          {paths.length} files, read-only. You start from exactly this.
        </span>
      </div>
      <div className={`${CARD} overflow-hidden flex flex-col lg:flex-row h-[36rem] lg:h-[32rem]`}>
        <nav
          aria-label="Files"
          className="shrink-0 lg:w-60 max-h-40 lg:max-h-none overflow-auto py-2 border-b lg:border-b-0 lg:border-r border-zinc-200 dark:border-zinc-800"
        >
          <FileTree nodes={tree} openPath={path ?? null} onOpen={setPath} />
        </nav>
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
          <p className="shrink-0 h-9 flex items-center px-3 border-b border-zinc-200 dark:border-zinc-800 font-mono text-xs text-zinc-600 dark:text-zinc-400 truncate">
            {path}
          </p>
          <div className="relative flex-1 min-h-0 [--editor-bg:#fafafa] dark:[--editor-bg:#09090b] bg-[var(--editor-bg)]">
            {path != null && (
              <CodeMirror
                key={path}
                value={files[path]}
                theme={isDark ? 'dark' : 'light'}
                height="100%"
                className="h-full"
                readOnly
                extensions={extensions}
                basicSetup={{ foldGutter: false, highlightActiveLine: false, highlightActiveLineGutter: false }}
              />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function AppPreview({ projectId }: { projectId: string }) {
  const api = useMemo(() => generatedPreviewApi(projectId), [projectId]);
  const [status, setStatus] = useState<GeneratedPreviewStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Only a preview this page started is stopped when the page goes away.
  const startedHere = useRef(false);

  useEffect(() => {
    getGeneratedPreview(projectId).then(setStatus, (err) => setError(message(err, 'Could not load the preview.')));
  }, [projectId]);

  useEffect(
    () => () => {
      if (startedHere.current) stopGeneratedPreview(projectId);
    },
    [projectId],
  );

  async function start() {
    setStarting(true);
    setError(null);
    try {
      setStatus(await startGeneratedPreview(projectId));
      startedHere.current = true;
    } catch (err) {
      setError(message(err, 'Could not start the app.'));
    } finally {
      setStarting(false);
    }
  }

  const running = status?.state === 'running' && status.base != null;
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <p className={`${SECTION_TITLE} !mb-0`}>THE APP</p>
        <span className="text-xs text-zinc-500">The baseline, running in a sandbox of its own.</span>
      </div>
      <div className={`${CARD} overflow-hidden h-[36rem]`}>
        {running ? (
          <PreviewPane api={api} initial={status} onStatus={(next) => setStatus({ ...status, ...next })} />
        ) : (
          <div className="h-full flex items-center justify-center p-6">
            <div className="max-w-sm text-center flex flex-col items-center gap-2">
              <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">See it running</p>
              <p className="text-sm text-zinc-500">
                Starts the app from this code. The first load compiles it, which can take a minute. It stops when
                you leave or start the round.
              </p>
              {error && <ErrorText>{error}</ErrorText>}
              <button onClick={() => void start()} disabled={starting || status == null} className={`${PRIMARY_BUTTON} mt-2`}>
                {starting ? 'Starting…' : status?.state === 'stopped' ? 'Resume the app' : 'Run the app'}
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
