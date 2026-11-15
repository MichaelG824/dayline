'use client';

import CodeMirror from '@uiw/react-codemirror';
import { Prec } from '@codemirror/state';
import { EditorView, keymap } from '@codemirror/view';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  InterviewerTrigger,
  MockSessionDetail,
  SandboxStatus,
  StagedRound,
  TestReport,
  WorkspaceFile,
  endLiveSession,
  getMockSession,
  getSandboxStatus,
  interviewerTurn,
  listWorkspaceFiles,
  readWorkspaceFile,
  resumeSandbox,
  runStageTests,
  runWorkspaceTests,
  skipStage,
  writeWorkspaceFile,
} from '../../lib/api';
import { FileNode, buildFileTree, formatClock, languageForPath } from '../../lib/mock';
import { useIsDark } from '../../lib/useIsDark';
import { languageExtensions } from '../problems/CodeEditor';
import { MarkdownView } from '../problems/Markdown';
import { AssistantPanel } from './AssistantPanel';
import { StagePanel } from './StagePanel';
import { TestResults, reportCounts } from './TestResults';
import { ErrorText } from './ui';

// xterm touches `window` at import time, so it only loads in the browser.
const Terminal = dynamic(() => import('./Terminal').then((m) => m.Terminal), { ssr: false });

const AUTOSAVE_MS = 1000;
const FILE_POLL_MS = 3000;
const SANDBOX_POLL_MS = 20_000;

interface OpenFile {
  path: string;
  content: string; // What the editor shows.
  saved: string; // What the sandbox has, as of `version`.
  version: string;
  saving: boolean;
  // The file changed on disk (e.g. from the terminal) while edited here.
  conflict: boolean;
  error: string | null;
}

type Panel = 'terminal' | 'tests';

const HEADER_BUTTON =
  'px-3 py-1.5 text-sm whitespace-nowrap rounded-md border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700 disabled:opacity-40';

// Prec.highest so it beats the light/dark theme's own background. The
// gutter must be opaque: long lines scroll sideways underneath it.
const editorTheme = Prec.highest(
  EditorView.theme({
    '&': { height: '100%', backgroundColor: 'var(--editor-bg)', fontSize: '0.8rem' },
    '&.cm-focused': { outline: 'none' },
    '.cm-scroller': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' },
    '.cm-gutters': { backgroundColor: 'var(--editor-bg)', border: 'none' },
  }),
);

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

interface Props {
  sessionId: string;
  onExit: () => void;
  onEnded: (sessionId: string) => void;
}

// The live-session workspace: files, editor, terminal, tests, and the task,
// filling the window like a coding-interview pad. Edits autosave to the
// sandbox; a file changed underneath (from the terminal) is reloaded when
// clean and flagged as a conflict when there are unsaved edits.
//
// A staged round swaps the task for the stage panel (progress, the active
// stage's prompt, the interviewer chat), and Run tests runs the active
// stage's hidden tests, which unlock the next stage when they pass.
export function Workspace({ sessionId, onExit, onEnded }: Props) {
  const [session, setSession] = useState<MockSessionDetail | null>(null);
  const [sandbox, setSandbox] = useState<SandboxStatus | null>(null);
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [open, setOpenState] = useState<OpenFile | null>(null);
  const [report, setReport] = useState<TestReport | null>(null);
  const [running, setRunning] = useState(false);
  const [panel, setPanel] = useState<Panel>('terminal');
  // Bumped on every tab click, so clicking TERMINAL focuses the shell even
  // when it is already the open tab.
  const [panelClicks, setPanelClicks] = useState(0);
  const [showTask, setShowTask] = useState(true);
  // The AI assistant (AI-assisted rounds); shares the side with the task.
  const [showAssistant, setShowAssistant] = useState(false);
  const [staged, setStaged] = useState<StagedRound | null>(null);
  const [thinking, setThinking] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  // What to resend when "Try again" is clicked after a failed interviewer turn.
  const lastTurn = useRef<{ trigger: InterviewerTrigger; message?: string } | null>(null);
  const [skipping, setSkipping] = useState<'idle' | 'confirm' | 'skipping'>('idle');
  const [ending, setEnding] = useState<'idle' | 'confirm' | 'ending'>('idle');
  const [resuming, setResuming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const isDark = useIsDark();
  // A parent callback that may change identity every render; effects call
  // the latest one without re-running.
  const onEndedRef = useRef(onEnded);
  useEffect(() => {
    onEndedRef.current = onEnded;
  }, [onEnded]);

  // The open file is read from timers and async callbacks, so keep a ref in
  // step with the state.
  const openRef = useRef<OpenFile | null>(null);
  const setOpen = useCallback((next: OpenFile | null) => {
    openRef.current = next;
    setOpenState(next);
  }, []);
  const patchOpen = useCallback(
    (path: string, patch: Partial<OpenFile>) => {
      const current = openRef.current;
      if (current && current.path === path) setOpen({ ...current, ...patch });
    },
    [setOpen],
  );

  const sandboxRunning = sandbox?.state === 'running';

  const refreshSandbox = useCallback(async () => {
    try {
      setSandbox(await getSandboxStatus(sessionId));
    } catch (err) {
      setError(errorMessage(err, 'Could not reach the sandbox.'));
    }
  }, [sessionId]);

  const openFile = useCallback(
    async (path: string) => {
      try {
        const file = await readWorkspaceFile(sessionId, path);
        setOpen({
          path,
          content: file.content,
          saved: file.content,
          version: file.version,
          saving: false,
          conflict: false,
          error: null,
        });
      } catch (err) {
        setError(errorMessage(err, `Could not open ${path}.`));
      }
    },
    [sessionId, setOpen],
  );

  // Saves run one at a time, each saving whatever the editor holds by then.
  const saveChain = useRef<Promise<void>>(Promise.resolve());
  const save = useCallback(
    (overwrite = false): Promise<void> => {
      const run = async () => {
        const file = openRef.current;
        if (!file || (file.content === file.saved && !overwrite) || (file.conflict && !overwrite)) return;
        const content = file.content;
        patchOpen(file.path, { saving: true });
        try {
          const result = await writeWorkspaceFile(
            sessionId,
            file.path,
            content,
            overwrite ? null : file.version,
          );
          patchOpen(file.path, {
            saved: content,
            version: result.version,
            saving: false,
            conflict: false,
            error: null,
          });
        } catch (err) {
          if (err instanceof ApiError && err.status === 409 && /changed/.test(err.message)) {
            patchOpen(file.path, { saving: false, conflict: true });
          } else {
            patchOpen(file.path, { saving: false, error: errorMessage(err, 'Could not save.') });
            if (err instanceof ApiError && err.status === 409) void refreshSandbox();
          }
        }
      };
      saveChain.current = saveChain.current.then(run);
      return saveChain.current;
    },
    [sessionId, patchOpen, refreshSandbox],
  );

  // First load: the session, its sandbox, and the README (the task) open.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const detail = await getMockSession(sessionId);
        if (cancelled) return;
        setSession(detail);
        setReport(detail.testReport ?? null);
        setStaged(detail.staged ?? null);
        if (detail.status !== 'live') {
          onEndedRef.current(sessionId);
          return;
        }
        const status = await getSandboxStatus(sessionId);
        if (cancelled) return;
        setSandbox(status);
        if (status.state === 'running') {
          const list = await listWorkspaceFiles(sessionId);
          if (cancelled) return;
          setFiles(list);
          const first = list.find((f) => f.path === detail.openPath) ?? list[0];
          if (first) await openFile(first.path);
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, 'Could not load the session.'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, openFile]);

  // Autosave shortly after typing stops.
  useEffect(() => {
    if (!open || open.content === open.saved || open.conflict) return;
    const timer = setTimeout(() => void save(), AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [open, save]);

  // Watch the file list (the terminal can add, change, or delete files).
  useEffect(() => {
    if (!sandboxRunning) return;
    const timer = setInterval(async () => {
      if (document.visibilityState !== 'visible') return;
      try {
        const list = await listWorkspaceFiles(sessionId);
        setFiles(list);
        const current = openRef.current;
        const entry = current && list.find((f) => f.path === current.path);
        if (current && entry && entry.version !== current.version && !current.saving) {
          if (current.content === current.saved) {
            const fresh = await readWorkspaceFile(sessionId, current.path);
            const latest = openRef.current;
            // Only replace it if nobody typed while we were reading.
            if (latest && latest.path === current.path && latest.content === latest.saved) {
              setOpen({ ...latest, content: fresh.content, saved: fresh.content, version: fresh.version });
            }
          } else {
            patchOpen(current.path, { conflict: true });
          }
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) void refreshSandbox();
      }
    }, FILE_POLL_MS);
    return () => clearInterval(timer);
  }, [sandboxRunning, sessionId, setOpen, patchOpen, refreshSandbox]);

  // The sandbox stops when idle or out of time; notice it.
  useEffect(() => {
    const timer = setInterval(() => void refreshSandbox(), SANDBOX_POLL_MS);
    return () => clearInterval(timer);
  }, [refreshSandbox]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Unsaved edits are lost if the tab closes before the autosave fires.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const file = openRef.current;
      if (file && file.content !== file.saved) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);

  async function switchTo(path: string) {
    if (openRef.current?.path === path) return;
    await save();
    await openFile(path);
  }

  // An accepted assistant edit was written: show it now rather than on the
  // next poll.
  const handleAssistantApplied = useCallback(
    async (path: string) => {
      try {
        setFiles(await listWorkspaceFiles(sessionId));
      } catch {
        // The poll will catch up.
      }
      const current = openRef.current;
      if (current?.path === path && current.content === current.saved) await openFile(path);
    },
    [sessionId, openFile],
  );

  async function reloadFromDisk() {
    const file = openRef.current;
    if (file) await openFile(file.path);
  }

  async function handleRunTests() {
    setPanel('tests');
    setRunning(true);
    setError(null);
    try {
      await save();
      setReport(await runWorkspaceTests(sessionId));
    } catch (err) {
      setError(errorMessage(err, 'Could not run the tests.'));
      if (err instanceof ApiError && err.status === 409) void refreshSandbox();
    } finally {
      setRunning(false);
    }
  }

  // One interviewer turn. The candidate's own message shows at once; the
  // round that comes back (with the reply) replaces it. A failed turn can be
  // retried: the server keeps a message even when the reply fails, and a
  // "message" turn without text replies to it.
  const askInterviewer = useCallback(
    async (trigger: InterviewerTrigger, message?: string) => {
      lastTurn.current = { trigger, message };
      setThinking(true);
      setChatError(null);
      if (message) {
        setStaged((prev) =>
          prev && {
            ...prev,
            chat: [
              ...prev.chat,
              { role: 'candidate', text: message, stage: prev.activeStage ?? 0, at: new Date().toISOString() },
            ],
          },
        );
      }
      try {
        await save();
        setStaged(await interviewerTurn(sessionId, trigger, message));
        lastTurn.current = null;
      } catch (err) {
        setChatError(errorMessage(err, 'The interviewer could not reply.'));
        try {
          const fresh = (await getMockSession(sessionId)).staged ?? null;
          setStaged(fresh);
          const last = fresh?.chat[fresh.chat.length - 1];
          if (message && last?.role === 'candidate' && last.text === message) {
            lastTurn.current = { trigger: 'message' };
          }
        } catch {
          // Keep what is on screen.
        }
      } finally {
        setThinking(false);
      }
    },
    [sessionId, save],
  );

  // The interviewer opens each stage (and closes the round) once; the server
  // ignores a repeat, so a reload or a double call is harmless.
  const opened = useRef<Set<number>>(new Set());
  useEffect(() => {
    if (!staged || session?.status !== 'live' || !sandboxRunning) return;
    const stage = staged.activeStage ?? 0;
    const said = staged.chat.some((m) => m.role === 'interviewer' && m.stage === stage);
    if (said || opened.current.has(stage)) return;
    opened.current.add(stage);
    void askInterviewer('stage_start');
  }, [staged, session?.status, sandboxRunning, askInterviewer]);

  async function handleRunStageTests() {
    setPanel('tests');
    setRunning(true);
    setError(null);
    try {
      await save();
      const run = await runStageTests(sessionId);
      setReport(run.report);
      setStaged(run.staged);
    } catch (err) {
      setError(errorMessage(err, 'Could not run the tests.'));
      if (err instanceof ApiError && err.status === 409) void refreshSandbox();
    } finally {
      setRunning(false);
    }
  }

  async function handleSkip() {
    if (skipping === 'idle') {
      setSkipping('confirm');
      return;
    }
    setSkipping('skipping');
    setError(null);
    try {
      await save();
      setStaged(await skipStage(sessionId));
      setReport(null);
    } catch (err) {
      setError(errorMessage(err, 'Could not skip the stage.'));
    } finally {
      setSkipping('idle');
    }
  }

  useEffect(() => {
    if (skipping !== 'confirm') return;
    const timer = setTimeout(() => setSkipping('idle'), 4000);
    return () => clearTimeout(timer);
  }, [skipping]);

  async function handleFinish() {
    setEnding('ending');
    setError(null);
    try {
      await save();
      await endLiveSession(sessionId);
      onEnded(sessionId);
    } catch (err) {
      setError(errorMessage(err, 'Could not finish the round.'));
      setEnding('idle');
    }
  }

  async function handleEnd() {
    if (ending === 'idle') {
      setEnding('confirm');
      return;
    }
    setEnding('ending');
    setError(null);
    try {
      if (sandboxRunning) await save();
      await endLiveSession(sessionId);
      onEnded(sessionId);
    } catch (err) {
      setError(errorMessage(err, 'Could not end the session.'));
      setEnding('idle');
    }
  }

  async function handleResume() {
    setResuming(true);
    setError(null);
    try {
      setSandbox(await resumeSandbox(sessionId));
      const list = await listWorkspaceFiles(sessionId);
      setFiles(list);
      const path = openRef.current?.path ?? list[0]?.path;
      if (path) await openFile(path);
    } catch (err) {
      setError(errorMessage(err, 'Could not resume the sandbox.'));
    } finally {
      setResuming(false);
    }
  }

  useEffect(() => {
    if (ending !== 'confirm') return;
    const timer = setTimeout(() => setEnding('idle'), 4000);
    return () => clearTimeout(timer);
  }, [ending]);

  const saveKeymap = useMemo(
    () =>
      Prec.highest(
        keymap.of([
          {
            key: 'Mod-s',
            run: () => {
              void save();
              return true;
            },
          },
        ]),
      ),
    [save],
  );
  const extensions = useMemo(
    () => [...languageExtensions(languageForPath(open?.path ?? '')), editorTheme, saveKeymap],
    [open?.path, saveKeymap],
  );
  const tree = useMemo(() => buildFileTree(files.map((f) => f.path)), [files]);

  const startedAt = session?.startedAt ? Date.parse(session.startedAt) : null;
  const elapsed = startedAt ? (now - startedAt) / 1000 : 0;
  const limit = (session?.durationMin ?? 0) * 60;
  const expiresAt = sandbox?.expiresAt ? Date.parse(sandbox.expiresAt) : null;
  const minutesLeft = expiresAt ? Math.floor((expiresAt - now) / 60_000) : null;
  const failing = report ? report.failed + report.errors : 0;

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 pt-[env(safe-area-inset-top,0px)]">
      <header className="flex items-center gap-2 sm:gap-3 px-4 h-12 shrink-0 border-b border-zinc-200 dark:border-zinc-800">
        <button
          onClick={onExit}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white whitespace-nowrap"
          title="Leave the session running and go back"
        >
          &lsaquo; Practice
        </button>
        <span className="h-4 w-px bg-zinc-200 dark:bg-zinc-800" />
        <h1 className="min-w-0 truncate text-sm font-medium">{session?.title ?? 'Loading…'}</h1>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-3">
          {minutesLeft != null && minutesLeft <= 10 && sandbox?.state === 'running' && (
            <span className="hidden md:inline text-xs text-amber-600 dark:text-amber-400 whitespace-nowrap">
              Sandbox stops in {Math.max(minutesLeft, 0)} min
            </span>
          )}
          {startedAt && (
            <span
              className={`font-mono text-sm tabular-nums whitespace-nowrap ${
                limit && elapsed > limit ? 'text-amber-600 dark:text-amber-400' : 'text-zinc-500'
              }`}
              title={limit ? `${session?.durationMin} minute round` : undefined}
            >
              {formatClock(elapsed)}
              {limit ? (
                <span className="hidden sm:inline text-zinc-400 dark:text-zinc-600"> / {formatClock(limit)}</span>
              ) : null}
            </span>
          )}
          {session?.assistant && (
            <button
              onClick={() => {
                setShowAssistant((v) => !v);
                setShowTask(false);
              }}
              className={`${HEADER_BUTTON} ${showAssistant ? 'bg-zinc-100 dark:bg-zinc-900' : ''}`}
              title="Your AI coding assistant: ask, plan, or edit"
            >
              <span className="sm:hidden">AI</span>
              <span className="hidden sm:inline">Assistant</span>
            </button>
          )}
          <button
            onClick={() => {
              setShowTask((v) => !v);
              setShowAssistant(false);
            }}
            className={`${staged ? '' : 'hidden lg:inline-block'} ${HEADER_BUTTON} ${
              showTask ? 'bg-zinc-100 dark:bg-zinc-900' : ''
            }`}
          >
            {staged ? 'Stage' : 'Task'}
          </button>
          <button
            onClick={() => void (staged ? handleRunStageTests() : handleRunTests())}
            disabled={!sandboxRunning || running || (staged != null && staged.activeStage == null)}
            className={HEADER_BUTTON}
            title={
              staged?.activeStage
                ? `Runs stage ${staged.activeStage}'s hidden tests, plus those of every stage you passed`
                : undefined
            }
          >
            {running ? 'Running…' : 'Run tests'}
          </button>
          <button
            onClick={() => void handleEnd()}
            disabled={ending === 'ending' || !session}
            className={`px-3 py-1.5 text-sm rounded-md whitespace-nowrap disabled:opacity-40 ${
              ending === 'confirm'
                ? 'bg-rose-500 hover:bg-rose-400 text-white'
                : 'bg-indigo-500 hover:bg-indigo-400 text-white'
            }`}
          >
            {/* Short on phones, where the header is tight. */}
            {ending === 'ending' ? (
              'Ending…'
            ) : ending === 'confirm' ? (
              <>
                Confirm<span className="hidden sm:inline"> end</span>
              </>
            ) : (
              <>
                End<span className="hidden sm:inline"> session</span>
              </>
            )}
          </button>
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-3 px-4 py-2 border-b border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/30">
          <ErrorText>{error}</ErrorText>
          <button onClick={() => setError(null)} className="ml-auto text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
            Dismiss
          </button>
        </div>
      )}

      <div className="relative flex-1 min-h-0 flex">
        <aside className="hidden md:flex w-56 shrink-0 flex-col border-r border-zinc-200 dark:border-zinc-800">
          <p className="px-4 pt-3 pb-2 font-mono text-xs tracking-widest text-zinc-500">FILES</p>
          <nav className="flex-1 overflow-y-auto pb-3 text-sm">
            <Tree nodes={tree} depth={0} openPath={open?.path ?? null} onOpen={(p) => void switchTo(p)} />
          </nav>
        </aside>

        <main className="flex-1 min-w-0 flex flex-col">
          <div className="flex items-center gap-3 h-9 shrink-0 px-3 border-b border-zinc-200 dark:border-zinc-800">
            <select
              value={open?.path ?? ''}
              onChange={(e) => void switchTo(e.target.value)}
              className="md:hidden min-w-0 flex-1 bg-transparent text-sm font-mono"
              aria-label="Open file"
            >
              {files.map((f) => (
                <option key={f.path} value={f.path}>
                  {f.path}
                </option>
              ))}
            </select>
            <span className="hidden md:block min-w-0 truncate font-mono text-xs text-zinc-600 dark:text-zinc-400">
              {open?.path ?? ''}
            </span>
            <span className="ml-auto shrink-0 font-mono text-xs text-zinc-400 dark:text-zinc-500">
              {open && (open.saving ? 'Saving…' : open.content !== open.saved ? 'Edited' : 'Saved')}
            </span>
          </div>

          {open?.conflict && (
            <div className="flex items-center gap-3 flex-wrap px-3 py-2 text-sm border-b border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30">
              <span className="text-amber-800 dark:text-amber-300">
                {open.path} changed on disk (from the terminal?) while you were editing.
              </span>
              <span className="ml-auto flex gap-3">
                <button onClick={() => void reloadFromDisk()} className="text-indigo-600 dark:text-indigo-400 hover:underline">
                  Load the disk version
                </button>
                <button onClick={() => void save(true)} className="text-indigo-600 dark:text-indigo-400 hover:underline">
                  Keep mine
                </button>
              </span>
            </div>
          )}
          {open?.error && !open.conflict && (
            <div className="px-3 py-2 border-b border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/30">
              <ErrorText>{open.error}</ErrorText>
            </div>
          )}

          <div className="relative flex-1 min-h-0 [--editor-bg:#fafafa] dark:[--editor-bg:#09090b] bg-[var(--editor-bg)]">
            {open && (
              <CodeMirror
                key={open.path}
                value={open.content}
                onChange={(value) => {
                  const current = openRef.current;
                  if (current) setOpen({ ...current, content: value });
                }}
                theme={isDark ? 'dark' : 'light'}
                height="100%"
                className="h-full"
                editable={sandboxRunning}
                extensions={extensions}
                basicSetup={{ foldGutter: false }}
              />
            )}
            {sandbox && sandbox.state !== 'running' && (
              <SandboxStopped
                status={sandbox}
                expired={expiresAt != null && now >= expiresAt}
                resuming={resuming}
                onResume={() => void handleResume()}
                onEnd={() => void handleEnd()}
              />
            )}
          </div>

          <div className="h-[38%] min-h-44 shrink-0 flex flex-col border-t border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-1 h-9 shrink-0 px-2 border-b border-zinc-200 dark:border-zinc-800">
              {(['terminal', 'tests'] as Panel[]).map((p) => (
                <button
                  key={p}
                  onClick={() => {
                    setPanel(p);
                    setPanelClicks((n) => n + 1);
                  }}
                  className={`px-3 py-1 text-xs font-mono rounded-md ${
                    panel === p
                      ? 'bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  {p === 'terminal' ? 'TERMINAL' : 'TESTS'}
                  {p === 'tests' && report && !running && (
                    <span
                      className={`ml-2 ${
                        failing ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400'
                      }`}
                    >
                      {failing ? `${failing} failing` : report.status === 'passed' ? 'passing' : report.status}
                    </span>
                  )}
                </button>
              ))}
              {report && panel === 'tests' && (
                <span className="ml-auto pr-2 font-mono text-xs text-zinc-400 dark:text-zinc-500">
                  {reportCounts(report)}
                </span>
              )}
            </div>
            <div className="relative flex-1 min-h-0">
              <div className={`absolute inset-0 ${panel === 'terminal' ? '' : 'invisible'}`}>
                {sandboxRunning && <Terminal sessionId={sessionId} active={panel === 'terminal'} focusKey={panelClicks} />}
              </div>
              {panel === 'tests' && (
                <div className="absolute inset-0 overflow-y-auto">
                  <TestResults report={report} running={running} />
                </div>
              )}
            </div>
          </div>
        </main>

        {showTask && staged && (
          <aside className="absolute inset-0 z-10 sm:left-auto sm:w-[26rem] sm:border-l sm:shadow-xl lg:static lg:z-auto lg:shadow-none shrink-0 border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
            <StagePanel
              staged={staged}
              now={now}
              thinking={thinking}
              chatError={chatError}
              skipping={skipping}
              finishing={ending === 'ending'}
              onSend={(text) => void askInterviewer('message', text)}
              onFollowUp={() => void askInterviewer('follow_up')}
              onRetry={() => {
                const turn = lastTurn.current ?? { trigger: 'follow_up' as const };
                void askInterviewer(turn.trigger, turn.message);
              }}
              onSkip={() => void handleSkip()}
              onFinish={() => void handleFinish()}
              onClose={() => setShowTask(false)}
            />
          </aside>
        )}
        {session?.assistant && (
          // Kept mounted while hidden, so a reply keeps streaming.
          <aside
            className={`${
              showAssistant ? '' : 'hidden'
            } absolute inset-0 z-10 sm:left-auto sm:w-[26rem] sm:border-l sm:shadow-xl lg:static lg:z-auto lg:shadow-none xl:w-[30rem] shrink-0 border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950`}
          >
            <AssistantPanel
              sessionId={sessionId}
              open={showAssistant}
              enabled={sandboxRunning}
              beforeSend={save}
              onApplied={(path) => void handleAssistantApplied(path)}
              onOpenFile={(path) => {
                void switchTo(path);
                // Below lg the panel covers the editor: get out of the way.
                if (!window.matchMedia('(min-width: 1024px)').matches) setShowAssistant(false);
              }}
              onClose={() => setShowAssistant(false)}
            />
          </aside>
        )}
        {showTask && !staged && (
          <aside className="hidden lg:block w-[24rem] shrink-0 overflow-y-auto border-l border-zinc-200 dark:border-zinc-800 px-5 py-4">
            <MarkdownView empty="No task description.">{session?.taskMd ?? ''}</MarkdownView>
          </aside>
        )}
      </div>
    </div>
  );
}

function Tree({
  nodes,
  depth,
  openPath,
  onOpen,
}: {
  nodes: FileNode[];
  depth: number;
  openPath: string | null;
  onOpen: (path: string) => void;
}) {
  return (
    <ul>
      {nodes.map((node) => (
        <li key={node.path}>
          {node.children ? (
            <>
              <p
                className="py-1 pr-3 font-mono text-xs text-zinc-500 truncate"
                style={{ paddingLeft: `${1 + depth * 0.75}rem` }}
              >
                {node.name}/
              </p>
              <Tree nodes={node.children} depth={depth + 1} openPath={openPath} onOpen={onOpen} />
            </>
          ) : (
            <button
              onClick={() => onOpen(node.path)}
              className={`block w-full text-left py-1 pr-3 font-mono text-xs truncate ${
                node.path === openPath
                  ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-900'
              }`}
              style={{ paddingLeft: `${1 + depth * 0.75}rem` }}
              title={node.path}
            >
              {node.name}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function SandboxStopped({
  status,
  expired,
  resuming,
  onResume,
  onEnd,
}: {
  status: SandboxStatus;
  expired: boolean;
  resuming: boolean;
  onResume: () => void;
  onEnd: () => void;
}) {
  const gone = status.state === 'gone';
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-white/70 dark:bg-zinc-950/70 backdrop-blur-[1px]">
      <div className="max-w-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 text-sm shadow-sm flex flex-col gap-3">
        <p className="font-medium">
          {gone ? 'The sandbox was deleted' : expired ? 'Time is up' : 'The sandbox went to sleep'}
        </p>
        <p className="text-zinc-500">
          {gone
            ? 'Its files are gone. End the session to keep the timeline and test results.'
            : expired
              ? 'The sandbox reached its time limit. Your files are kept: end the session to save them.'
              : `Nothing happened for ${Math.round((status.idleTimeoutS ?? 900) / 60)} minutes, so it was paused. Your files are kept.`}
        </p>
        <div className="flex gap-2">
          {!gone && !expired && (
            <button
              onClick={onResume}
              disabled={resuming}
              className="px-3 py-1.5 text-sm rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
            >
              {resuming ? 'Resuming…' : 'Resume'}
            </button>
          )}
          <button onClick={onEnd} className={HEADER_BUTTON}>
            End session
          </button>
        </div>
      </div>
    </div>
  );
}
