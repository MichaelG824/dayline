'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  DevServer,
  DevServerState,
  PreviewStatus,
  ServerAction,
  devServerAction,
  getPreviewStatus,
  getServerLogs,
  notePreviewReloaded,
  previewUrl,
} from '../../lib/api';

const STATUS_POLL_MS = 5000;
const STARTING_POLL_MS = 1500;
const LOG_POLL_MS = 1500;
const MAX_LOG_LINES = 1000;

// Matches the Content-Security-Policy sandbox the API sends with the app.
const IFRAME_SANDBOX =
  'allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads';

const DOT: Record<DevServerState, string> = {
  ready: 'bg-emerald-500',
  starting: 'bg-amber-500 animate-pulse',
  exited: 'bg-rose-500',
  stopped: 'bg-zinc-300 dark:bg-zinc-600',
};

const ICON_BUTTON =
  'shrink-0 inline-flex items-center justify-center h-7 w-7 rounded-md text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-zinc-900 disabled:opacity-40 disabled:pointer-events-none';

const TEXT_BUTTON =
  'px-2 py-0.5 text-xs rounded-md text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-zinc-900 disabled:opacity-40';

export function stateLabel(server: DevServer): string {
  switch (server.state) {
    case 'ready':
      return 'Running';
    case 'starting':
      return 'Starting…';
    case 'exited':
      return server.exitCode != null ? `Exited (code ${server.exitCode})` : 'Exited';
    default:
      return 'Stopped';
  }
}

// The server to preview first: the one named "web", else the first.
function defaultServer(servers: DevServer[]): string | null {
  return (servers.find((s) => s.name === 'web') ?? servers[0])?.name ?? null;
}

interface Props {
  sessionId: string;
  // The status the workspace already loaded (it decides whether to offer a
  // preview at all); the pane keeps it fresh while open.
  initial: PreviewStatus;
  onStatus: (status: PreviewStatus) => void;
  onClose: () => void;
}

// The running app beside the editor: pick a dev server, see it in a
// sandboxed iframe, reload it or open it in a tab, restart the server, and
// read its logs.
export function PreviewPane({ sessionId, initial, onStatus, onClose }: Props) {
  const [status, setStatus] = useState<PreviewStatus>(initial);
  const [selected, setSelected] = useState<string | null>(() => defaultServer(initial.servers));
  const [path, setPath] = useState('/');
  const [draftPath, setDraftPath] = useState('/');
  const [frameKey, setFrameKey] = useState(0);
  const [busy, setBusy] = useState<ServerAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logsOpen, setLogsOpen] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const logCursor = useRef(0);
  const logBox = useRef<HTMLPreElement>(null);
  const stickToBottom = useRef(true);

  const server = status.servers.find((s) => s.name === selected) ?? null;
  const anyStarting = status.servers.some((s) => s.state === 'starting');

  const apply = useCallback(
    (next: PreviewStatus) => {
      setStatus(next);
      onStatus(next);
    },
    [onStatus],
  );

  // Keep the status fresh; faster while something is starting.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(
      async () => {
        try {
          const next = await getPreviewStatus(sessionId);
          if (!cancelled) apply(next);
        } catch {
          // The workspace notices a stopped sandbox itself.
        }
      },
      anyStarting ? STARTING_POLL_MS : STATUS_POLL_MS,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId, status, anyStarting, apply]);

  // A server that just became ready replaces whatever the frame showed.
  const lastState = useRef<DevServerState | null>(server?.state ?? null);
  useEffect(() => {
    if (server?.state === 'ready' && lastState.current !== 'ready') setFrameKey((k) => k + 1);
    lastState.current = server?.state ?? null;
  }, [server?.state]);

  // Logs for the selected server, from the start, while the drawer is open.
  useEffect(() => {
    if (!logsOpen || !selected) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const chunk = await getServerLogs(sessionId, selected, logCursor.current);
        if (cancelled) return;
        logCursor.current = chunk.next;
        if (chunk.lines.length || chunk.truncated) {
          setLogs((prev) =>
            [...prev, ...(chunk.truncated && prev.length ? ['…'] : []), ...chunk.lines].slice(-MAX_LOG_LINES),
          );
        }
      } catch {
        // Try again on the next tick.
      }
      if (!cancelled) timer = setTimeout(poll, LOG_POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId, selected, logsOpen]);

  useEffect(() => {
    logCursor.current = 0;
    setLogs([]);
  }, [selected]);

  useEffect(() => {
    const box = logBox.current;
    if (box && stickToBottom.current) box.scrollTop = box.scrollHeight;
  }, [logs, logsOpen]);

  async function act(action: ServerAction) {
    if (!server) return;
    setBusy(action);
    setError(null);
    try {
      apply(await devServerAction(sessionId, server.name, action));
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not ${action} ${server.name}.`);
    } finally {
      setBusy(null);
    }
  }

  function reload() {
    if (!server) return;
    setFrameKey((k) => k + 1);
    void notePreviewReloaded(sessionId, server.name);
  }

  function navigate(event: FormEvent) {
    event.preventDefault();
    const next = draftPath.trim() || '/';
    const normalised = next.startsWith('/') ? next : `/${next}`;
    setDraftPath(normalised);
    setPath(normalised);
    setFrameKey((k) => k + 1);
  }

  function choose(name: string) {
    setSelected(name);
    setPath('/');
    setDraftPath('/');
  }

  const url = status.base && server ? previewUrl(status.base, server.port, path) : null;

  return (
    <div className="h-full flex flex-col min-h-0 bg-white dark:bg-zinc-950">
      <div className="flex items-center gap-2 h-9 shrink-0 pl-3 pr-1.5 border-b border-zinc-200 dark:border-zinc-800">
        <p className="font-mono text-xs tracking-widest text-zinc-500">PREVIEW</p>
        <div className="flex items-center gap-1 min-w-0 overflow-x-auto" role="tablist" aria-label="Dev servers">
          {status.servers.map((s) => (
            <button
              key={s.name}
              role="tab"
              aria-selected={s.name === selected}
              onClick={() => choose(s.name)}
              title={`${s.name} on port ${s.port}: ${stateLabel(s)}`}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md font-mono text-xs whitespace-nowrap ${
                s.name === selected
                  ? 'bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${DOT[s.state]}`} />
              {s.name}
              <span className="text-zinc-400 dark:text-zinc-500">:{s.port}</span>
            </button>
          ))}
        </div>
        <button onClick={onClose} className={`ml-auto ${ICON_BUTTON}`} aria-label="Close the preview" title="Close">
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>

      <form onSubmit={navigate} className="flex items-center gap-1 h-10 shrink-0 px-2 border-b border-zinc-200 dark:border-zinc-800">
        <button type="button" onClick={reload} disabled={!url} className={ICON_BUTTON} aria-label="Reload the preview" title="Reload">
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M13 8a5 5 0 1 1-1.46-3.54" />
            <path d="M13 2.5V5h-2.5" />
          </svg>
        </button>
        <label className="sr-only" htmlFor="preview-path">
          Path
        </label>
        <input
          id="preview-path"
          value={draftPath}
          onChange={(e) => setDraftPath(e.target.value)}
          spellCheck={false}
          autoComplete="off"
          disabled={!url}
          className="min-w-0 flex-1 h-7 px-2.5 rounded-md bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 font-mono text-xs text-zinc-700 dark:text-zinc-300 focus:outline-none focus:border-indigo-400 dark:focus:border-indigo-500 disabled:opacity-60"
        />
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer" className={ICON_BUTTON} aria-label="Open in a new tab" title="Open in a new tab">
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 3h4v4M13 3L7.5 8.5M11 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2.5" />
            </svg>
          </a>
        ) : (
          <span className={`${ICON_BUTTON} opacity-40`} aria-hidden="true">
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 3h4v4M13 3L7.5 8.5M11 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2.5" />
            </svg>
          </span>
        )}
      </form>

      <div className="relative flex-1 min-h-0 bg-zinc-50 dark:bg-zinc-900/40">
        {url && server?.state === 'ready' ? (
          <iframe
            key={`${server.name}-${frameKey}`}
            src={url}
            title={`Preview of ${server.name}`}
            sandbox={IFRAME_SANDBOX}
            className="absolute inset-0 h-full w-full border-0 bg-white"
          />
        ) : (
          <FrameState
            server={server}
            hasBase={status.base != null}
            busy={busy}
            onStart={() => void act('start')}
            onLogs={() => setLogsOpen(true)}
          />
        )}
      </div>

      {error && (
        <p className="shrink-0 px-3 py-1.5 text-xs text-rose-600 dark:text-rose-400 border-t border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/30">
          {error}
        </p>
      )}

      <div className="shrink-0 border-t border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-2 h-9 pl-1.5 pr-1.5">
          <button
            onClick={() => setLogsOpen((v) => !v)}
            aria-expanded={logsOpen}
            className="flex items-center gap-1.5 px-1.5 py-0.5 rounded-md font-mono text-xs tracking-widest text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
          >
            <svg
              viewBox="0 0 16 16"
              className={`h-3 w-3 transition-transform ${logsOpen ? 'rotate-90' : ''}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 4l4 4-4 4" />
            </svg>
            LOGS
          </button>
          {server && (
            <span className="min-w-0 truncate text-xs text-zinc-500">
              {server.name} · {stateLabel(server)}
            </span>
          )}
          {server && (
            <span className="ml-auto flex items-center gap-0.5">
              <button onClick={() => void act('restart')} disabled={busy != null} className={TEXT_BUTTON}>
                {busy === 'restart' ? 'Restarting…' : 'Restart'}
              </button>
              {server.state === 'ready' || server.state === 'starting' ? (
                <button onClick={() => void act('stop')} disabled={busy != null} className={TEXT_BUTTON}>
                  {busy === 'stop' ? 'Stopping…' : 'Stop'}
                </button>
              ) : (
                <button onClick={() => void act('start')} disabled={busy != null} className={TEXT_BUTTON}>
                  {busy === 'start' ? 'Starting…' : 'Start'}
                </button>
              )}
            </span>
          )}
        </div>
        {logsOpen && (
          <pre
            ref={logBox}
            onScroll={(e) => {
              const box = e.currentTarget;
              stickToBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
            }}
            className="h-44 overflow-auto px-3 pb-2 font-mono text-[11px] leading-[1.15rem] text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words"
          >
            {logs.length ? logs.join('\n') : <span className="text-zinc-400 dark:text-zinc-500">No output yet.</span>}
          </pre>
        )}
      </div>
    </div>
  );
}

function FrameState({
  server,
  hasBase,
  busy,
  onStart,
  onLogs,
}: {
  server: DevServer | null;
  hasBase: boolean;
  busy: ServerAction | null;
  onStart: () => void;
  onLogs: () => void;
}) {
  let title: string;
  let body: string;
  let canStart = false;
  if (!hasBase) {
    title = 'No preview for this session';
    body = 'It started before live previews existed. Start a new session to see the app here.';
  } else if (!server) {
    title = 'No dev servers';
    body = 'This sandbox has nothing to preview.';
  } else if (server.state === 'starting') {
    title = `Starting ${server.name}…`;
    body = 'The first start compiles the app, which can take a minute.';
  } else if (server.state === 'exited') {
    title = `${server.name} stopped`;
    body =
      server.exitCode != null
        ? `It exited with code ${server.exitCode}. The logs say why; fix it and start it again.`
        : 'It is no longer running. The logs say why.';
    canStart = true;
  } else {
    title = `${server.name} is not running`;
    body = 'Start it to see the app.';
    canStart = true;
  }
  return (
    <div className="absolute inset-0 flex items-center justify-center p-6">
      <div className="max-w-xs text-center flex flex-col items-center gap-2">
        {server?.state === 'starting' && (
          <span className="mb-1 h-5 w-5 rounded-full border-2 border-zinc-300 dark:border-zinc-700 border-t-indigo-500 dark:border-t-indigo-400 animate-spin" />
        )}
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{title}</p>
        <p className="text-sm text-zinc-500">{body}</p>
        {server && (
          <div className="mt-2 flex items-center gap-2">
            {canStart && (
              <button
                onClick={onStart}
                disabled={busy != null}
                className="px-3 py-1.5 text-sm rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
              >
                {busy === 'start' ? 'Starting…' : `Start ${server.name}`}
              </button>
            )}
            <button
              onClick={onLogs}
              className="px-3 py-1.5 text-sm rounded-md border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700"
            >
              Show logs
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
