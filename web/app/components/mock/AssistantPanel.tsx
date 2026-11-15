'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AssistantMode,
  AssistantProposal,
  AssistantTurn,
  cancelAssistantTurn,
  decideAssistantEdit,
  getAssistant,
  streamAssistantTurn,
} from '../../lib/assistant';
import { MarkdownView } from '../problems/Markdown';
import { DiffView } from './DiffView';

const MODES: { mode: AssistantMode; label: string; hint: string; placeholder: string }[] = [
  {
    mode: 'ask',
    label: 'Ask',
    hint: 'Read-only answers about the code.',
    placeholder: 'Ask about the code…',
  },
  {
    mode: 'plan',
    label: 'Plan',
    hint: 'A step-by-step plan. No changes.',
    placeholder: 'Describe what you want to fix or build…',
  },
  {
    mode: 'edit',
    label: 'Edit',
    hint: 'Drafts diffs you accept or reject.',
    placeholder: 'Describe the change to make…',
  },
];

// If the server has not stopped a turn this long after Stop, drop the
// connection instead.
const STOP_GRACE_MS = 4000;
const RUNNING_POLL_MS = 3000;

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

interface Props {
  sessionId: string;
  // The panel is on screen (it stays mounted while hidden).
  open: boolean;
  // The sandbox is up (prompts and edits need it).
  enabled: boolean;
  // Save the editor first, so the assistant reads (and edits) what is on screen.
  beforeSend: () => Promise<void>;
  // An accepted edit was written to `path`.
  onApplied: (path: string) => void;
  onOpenFile: (path: string) => void;
  onClose: () => void;
}

// What is on screen for the turn being streamed.
interface Live {
  turnId: string | null;
  turn: AssistantTurn;
  status: string | null;
  stopping: boolean;
}

// The in-session coding assistant: a mode switch (ask / plan / edit), the
// conversation, and a diff to accept or reject for every edit it drafts.
// Every prompt, reply, and decision is recorded on the session.
export function AssistantPanel({ sessionId, open, enabled, beforeSend, onApplied, onOpenFile, onClose }: Props) {
  const [mode, setMode] = useState<AssistantMode>('ask');
  const [model, setModel] = useState<string | null>(null);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [remoteRunning, setRemoteRunning] = useState(false);
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<{ message: string; retry: { mode: AssistantMode; prompt: string } | null } | null>(
    null,
  );
  const [draft, setDraft] = useState('');
  // Proposal id -> the decision being saved.
  const [busy, setBusy] = useState<Map<string, 'accept' | 'reject'>>(new Map());
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stuckToBottom = useRef(true);
  // Where we last scrolled to: the scroll event that move fires can arrive
  // after more content landed, and must not read as the reader scrolling up.
  const autoTop = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const state = await getAssistant(sessionId);
      setModel(state.model);
      setTurns(state.turns);
      setRemoteRunning(state.running);
    } catch (err) {
      setError({ message: errorMessage(err, 'Could not load the assistant.'), retry: null });
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // A turn started elsewhere (another tab): show it when it lands.
  useEffect(() => {
    if (!remoteRunning || live) return;
    const timer = setInterval(() => void load(), RUNNING_POLL_MS);
    return () => clearInterval(timer);
  }, [remoteRunning, live, load]);

  // Follow new output, unless the reader scrolled up.
  useEffect(() => {
    const el = scroller.current;
    if (el && stuckToBottom.current) {
      el.scrollTop = el.scrollHeight;
      autoTop.current = el.scrollTop;
    }
  }, [turns, live, error, open]);

  useEffect(() => () => abort.current?.abort(), []);

  const streaming = live != null;

  async function send(sendMode: AssistantMode, text: string) {
    const prompt = text.trim();
    if (!prompt || streaming || !enabled) return;
    setError(null);
    stuckToBottom.current = true;
    const placeholder: AssistantTurn = {
      turn: -1,
      mode: sendMode,
      prompt,
      reply: '',
      status: 'running',
      error: null,
      tools: [],
      durationMs: null,
      at: new Date().toISOString(),
      proposals: [],
    };
    setLive({ turnId: null, turn: placeholder, status: 'Reading your code…', stopping: false });
    const patch = (fn: (turn: AssistantTurn) => Partial<AssistantTurn>, status?: string | null) =>
      setLive((prev) =>
        prev && {
          ...prev,
          turn: { ...prev.turn, ...fn(prev.turn) },
          status: status === undefined ? prev.status : status,
        },
      );
    const controller = new AbortController();
    abort.current = controller;
    let finished = false;
    const finish = (turn: AssistantTurn | null) => {
      finished = true;
      if (turn) setTurns((prev) => [...prev.filter((t) => t.turn !== turn.turn), turn]);
      setLive(null);
    };
    try {
      await beforeSend();
      await streamAssistantTurn(
        sessionId,
        sendMode,
        prompt,
        {
          onStart: (turnId, turn) => setLive((prev) => prev && { ...prev, turnId, turn: { ...prev.turn, turn } }),
          onDelta: (chunk) => patch((t) => ({ reply: t.reply + chunk }), null),
          onStatus: (message) => patch(() => ({}), message),
          onTool: (summary) => patch((t) => ({ tools: [...t.tools, summary] })),
          onProposal: (proposal) =>
            patch((t) => ({ proposals: [...t.proposals.filter((p) => p.id !== proposal.id), proposal] })),
          onDone: (turn) => finish(turn),
          onError: (message, turn) => {
            finish(turn);
            setError({ message, retry: { mode: sendMode, prompt } });
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (controller.signal.aborted) {
        // Stopped by dropping the connection: the server records it as
        // stopped; fetch the recorded turn once it has.
        setLive(null);
        setTimeout(() => void load(), 1000);
        return;
      }
      setLive(null);
      setError({ message: errorMessage(err, 'The assistant could not reply.'), retry: { mode: sendMode, prompt } });
      void load();
    } finally {
      if (abort.current === controller) abort.current = null;
      if (!finished && !controller.signal.aborted) setLive(null);
    }
  }

  function submit() {
    const text = draft.trim();
    if (!text || streaming || !enabled) return;
    setDraft('');
    void send(mode, text);
  }

  async function stop() {
    if (!live || live.stopping) return;
    setLive({ ...live, stopping: true, status: 'Stopping…' });
    const controller = abort.current;
    const turnId = live.turnId;
    setTimeout(() => {
      if (abort.current === controller) controller?.abort();
    }, STOP_GRACE_MS);
    if (turnId) {
      try {
        await cancelAssistantTurn(sessionId, turnId);
        return;
      } catch {
        // Fall through: drop the connection now.
      }
    }
    controller?.abort();
  }

  const setProposal = (proposal: AssistantProposal) =>
    setTurns((prev) =>
      prev.map((t) => ({ ...t, proposals: t.proposals.map((p) => (p.id === proposal.id ? proposal : p)) })),
    );

  async function decide(proposal: AssistantProposal, decision: 'accept' | 'reject') {
    setBusy((prev) => new Map(prev).set(proposal.id, decision));
    setError(null);
    try {
      if (decision === 'accept') await beforeSend();
      const updated = await decideAssistantEdit(sessionId, proposal.id, decision);
      setProposal(updated);
      if (updated.status === 'accepted') onApplied(updated.path);
    } catch (err) {
      setError({ message: errorMessage(err, 'Could not update the edit.'), retry: null });
      void load();
    } finally {
      setBusy((prev) => {
        const next = new Map(prev);
        next.delete(proposal.id);
        return next;
      });
    }
  }

  async function decideAll(proposals: AssistantProposal[], decision: 'accept' | 'reject') {
    for (const proposal of proposals) await decide(proposal, decision);
  }

  const current = MODES.find((m) => m.mode === mode) ?? MODES[0];
  const shown = live ? [...turns, live.turn] : turns;

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="shrink-0 px-4 pt-3 pb-3 border-b border-zinc-200 dark:border-zinc-800 flex flex-col gap-2.5">
        <div className="flex items-center gap-2">
          <p className="font-mono text-xs tracking-widest text-zinc-500">AI ASSISTANT</p>
          {model && (
            <span className="min-w-0 truncate font-mono text-[0.7rem] text-zinc-400 dark:text-zinc-500" title="Model">
              {model}
            </span>
          )}
          <button
            onClick={onClose}
            className="lg:hidden ml-auto -mr-1 px-1 text-lg leading-none text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
            aria-label="Close the assistant"
          >
            &times;
          </button>
        </div>
        {/* Two lines tall either way, so a wrapping hint never shifts the panel. */}
        <div className="flex items-center gap-3 min-h-[2.125rem]">
          <div role="radiogroup" aria-label="Assistant mode" className="flex shrink-0 rounded-lg bg-zinc-100 dark:bg-zinc-900 p-0.5">
            {MODES.map((m) => (
              <button
                key={m.mode}
                role="radio"
                aria-checked={mode === m.mode}
                onClick={() => setMode(m.mode)}
                className={`px-3 py-1 text-xs rounded-md ${
                  mode === m.mode
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="min-w-0 text-xs leading-snug text-zinc-500">{current.hint}</p>
        </div>
      </div>

      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          if (autoTop.current != null && Math.abs(el.scrollTop - autoTop.current) <= 1) return;
          autoTop.current = null;
          stuckToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="flex-1 min-h-0 overflow-y-auto px-4 py-4 flex flex-col gap-5"
      >
        {shown.length === 0 && !error && (
          <div className="text-sm text-zinc-500 flex flex-col gap-2">
            <p>Your coding assistant for this round. It can read every file, the last test run, and your terminal commands.</p>
            <p>
              <span className="text-zinc-700 dark:text-zinc-300">Ask</span> about the code,{' '}
              <span className="text-zinc-700 dark:text-zinc-300">Plan</span> a change, or let it{' '}
              <span className="text-zinc-700 dark:text-zinc-300">Edit</span>: you review every diff before anything is
              written. Your prompts and decisions are part of the session record.
            </p>
          </div>
        )}
        {shown.map((turn) => (
          <Turn
            key={turn.turn}
            turn={turn}
            live={live && turn === live.turn ? live : null}
            busy={busy}
            canDecide={enabled}
            onDecide={(p, d) => void decide(p, d)}
            onDecideAll={(ps, d) => void decideAll(ps, d)}
            onRedo={(p) =>
              void send(
                'edit',
                `Redo your edit to ${p.path}: the file changed after you proposed it. Read it again and propose the change against its current contents.`,
              )
            }
            onOpenFile={onOpenFile}
          />
        ))}
        {remoteRunning && !live && (
          <p className="text-xs text-zinc-500">The assistant is still answering a prompt from another tab…</p>
        )}
        {error && (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            {error.message}{' '}
            {error.retry && (
              <button
                onClick={() => error.retry && void send(error.retry.mode, error.retry.prompt)}
                disabled={streaming || !enabled}
                className="text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-40"
              >
                Try again
              </button>
            )}
          </p>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="shrink-0 flex items-end gap-2 px-3 py-3 border-t border-zinc-200 dark:border-zinc-800"
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={3}
          placeholder={enabled ? current.placeholder : 'The sandbox is not running.'}
          disabled={!enabled}
          aria-label={`Prompt the assistant (${current.label} mode)`}
          className="flex-1 min-w-0 resize-none bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm leading-snug disabled:opacity-60"
        />
        {streaming ? (
          <button
            type="button"
            onClick={() => void stop()}
            disabled={live?.stopping}
            className="px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700 disabled:opacity-40"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!draft.trim() || !enabled || remoteRunning}
            className="px-3 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
          >
            Send
          </button>
        )}
      </form>
    </div>
  );
}

const MODE_LABEL: Record<AssistantMode, string> = { ask: 'Ask', plan: 'Plan', edit: 'Edit' };

function Turn({
  turn,
  live,
  busy,
  canDecide,
  onDecide,
  onDecideAll,
  onRedo,
  onOpenFile,
}: {
  turn: AssistantTurn;
  live: Live | null;
  busy: Map<string, 'accept' | 'reject'>;
  canDecide: boolean;
  onDecide: (proposal: AssistantProposal, decision: 'accept' | 'reject') => void;
  onDecideAll: (proposals: AssistantProposal[], decision: 'accept' | 'reject') => void;
  onRedo: (proposal: AssistantProposal) => void;
  onOpenFile: (path: string) => void;
}) {
  const pending = turn.proposals.filter((p) => p.status === 'pending');
  const anyBusy = turn.proposals.some((p) => busy.has(p.id));
  return (
    <div className="flex flex-col gap-2.5">
      <div className="self-end max-w-[90%] flex flex-col items-end gap-1">
        <span className="font-mono text-[0.65rem] tracking-widest text-zinc-400 dark:text-zinc-500">
          {MODE_LABEL[turn.mode]?.toUpperCase() ?? turn.mode}
        </span>
        <div className="rounded-xl rounded-br-sm bg-indigo-500 text-white px-3 py-2 text-sm whitespace-pre-wrap break-words">
          {turn.prompt}
        </div>
      </div>

      {turn.tools.length > 0 && <ToolLog tools={turn.tools} open={live != null} />}

      {turn.reply ? (
        <div className="min-w-0 [overflow-wrap:anywhere]">
          <MarkdownView>{turn.reply}</MarkdownView>
        </div>
      ) : (
        !live &&
        turn.status === 'cancelled' && <p className="text-sm text-zinc-500">Stopped before it replied.</p>
      )}

      {live && live.status && (
        <p className="text-xs text-zinc-500 flex items-center gap-2" aria-live="polite">
          <span className="flex gap-0.5" aria-hidden>
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                className="w-1 h-1 rounded-full bg-zinc-400 animate-pulse"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </span>
          {live.status}
        </p>
      )}
      {!live && turn.status === 'cancelled' && turn.reply && <p className="text-xs text-zinc-500">Stopped.</p>}
      {!live && turn.status === 'error' && turn.error && !turn.reply && (
        <p className="text-xs text-zinc-500">No reply: {turn.error}</p>
      )}

      {turn.proposals.map((proposal) => (
        <ProposalCard
          key={proposal.id}
          proposal={proposal}
          drafting={live != null}
          busy={busy.get(proposal.id) ?? null}
          canDecide={canDecide && live == null}
          onDecide={(d) => onDecide(proposal, d)}
          onRedo={() => onRedo(proposal)}
          onOpenFile={() => onOpenFile(proposal.path)}
        />
      ))}

      {!live && pending.length > 1 && (
        <div className="flex items-center gap-3 text-xs">
          <span className="text-zinc-500">{pending.length} edits to review</span>
          <button
            onClick={() => onDecideAll(pending, 'reject')}
            disabled={anyBusy || !canDecide}
            className="ml-auto text-zinc-500 hover:text-rose-600 dark:hover:text-rose-400 disabled:opacity-40"
          >
            Reject all
          </button>
          <button
            onClick={() => onDecideAll(pending, 'accept')}
            disabled={anyBusy || !canDecide}
            className="text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-40 disabled:no-underline"
          >
            Accept all
          </button>
        </div>
      )}
    </div>
  );
}

// What the assistant looked at: collapsed to a count once the turn is done.
function ToolLog({ tools, open }: { tools: string[]; open: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const show = open || expanded;
  return (
    <div className="text-xs text-zinc-500">
      {!open && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="hover:text-zinc-900 dark:hover:text-zinc-200"
          aria-expanded={expanded}
        >
          {expanded ? '▾' : '▸'} {tools.length} {tools.length === 1 ? 'step' : 'steps'}
        </button>
      )}
      {show && (
        <ul className={`${open ? '' : 'mt-1'} flex flex-col gap-0.5 border-l border-zinc-200 dark:border-zinc-800 pl-2.5`}>
          {tools.map((tool, i) => (
            <li key={i} className="font-mono text-[0.7rem] leading-5 truncate" title={tool}>
              {tool}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const STATUS_BADGE: Record<AssistantProposal['status'], { label: string; className: string } | null> = {
  pending: null,
  accepted: { label: 'Applied', className: 'text-emerald-700 dark:text-emerald-400' },
  rejected: { label: 'Rejected', className: 'text-zinc-500' },
  conflict: { label: 'Not applied', className: 'text-amber-700 dark:text-amber-400' },
};

function ProposalCard({
  proposal,
  drafting,
  busy,
  canDecide,
  onDecide,
  onRedo,
  onOpenFile,
}: {
  proposal: AssistantProposal;
  drafting: boolean;
  busy: 'accept' | 'reject' | null;
  canDecide: boolean;
  onDecide: (decision: 'accept' | 'reject') => void;
  onRedo: () => void;
  onOpenFile: () => void;
}) {
  const decided = proposal.status === 'accepted' || proposal.status === 'rejected';
  const [open, setOpen] = useState(!decided);
  // Collapse once decided; a conflict stays open so its diff can be read.
  useEffect(() => {
    if (decided) setOpen(false);
  }, [decided]);
  const badge = STATUS_BADGE[proposal.status];
  return (
    <div
      className={`rounded-lg border ${
        proposal.status === 'conflict'
          ? 'border-amber-300 dark:border-amber-800/70'
          : 'border-zinc-200 dark:border-zinc-800'
      } bg-white dark:bg-zinc-900/40 overflow-hidden`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="shrink-0 w-4 text-xs text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
          aria-expanded={open}
          aria-label={open ? 'Hide the diff' : 'Show the diff'}
        >
          {open ? '▾' : '▸'}
        </button>
        <button
          onClick={onOpenFile}
          className="min-w-0 truncate font-mono text-xs text-zinc-800 dark:text-zinc-200 hover:underline"
          title={`Open ${proposal.path}`}
        >
          {proposal.path}
        </button>
        {proposal.newFile && (
          <span className="shrink-0 text-[0.65rem] font-mono px-1.5 py-px rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500">
            new
          </span>
        )}
        <span className="shrink-0 font-mono text-xs tabular-nums">
          <span className="text-emerald-600 dark:text-emerald-400">+{proposal.added}</span>{' '}
          <span className="text-rose-600 dark:text-rose-400">−{proposal.removed}</span>
        </span>
        {badge && <span className={`ml-auto shrink-0 text-xs font-medium ${badge.className}`}>{badge.label}</span>}
      </div>
      {proposal.summary && (
        <p className="px-3 pb-2 -mt-0.5 text-xs leading-snug text-zinc-600 dark:text-zinc-400">{proposal.summary}</p>
      )}
      {open && (
        <div className="max-h-80 overflow-auto border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-950/40">
          <DiffView diff={proposal.diff} fileHeaders={false} />
        </div>
      )}
      {proposal.status === 'conflict' && (
        <div className="px-3 py-2 border-t border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 text-xs text-amber-800 dark:text-amber-300 flex flex-col gap-1.5">
          <p>
            {proposal.path} changed after this edit was drafted, so it was not written. Nothing of yours was
            overwritten.
          </p>
          <div className="flex gap-3">
            <button
              onClick={onRedo}
              disabled={!canDecide}
              className="text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-40"
            >
              Redo against the current file
            </button>
            <button
              onClick={() => onDecide('reject')}
              disabled={busy != null || !canDecide}
              className="text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white disabled:opacity-40"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
      {proposal.status === 'pending' && !drafting && (
        <div className="flex items-center justify-end gap-2 px-3 py-2 border-t border-zinc-200 dark:border-zinc-800">
          <button
            onClick={() => onDecide('reject')}
            disabled={busy != null || !canDecide}
            className="px-2.5 py-1 text-xs rounded-md border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700 disabled:opacity-40"
          >
            {busy === 'reject' ? 'Rejecting…' : 'Reject'}
          </button>
          <button
            onClick={() => onDecide('accept')}
            disabled={busy != null || !canDecide}
            className="px-2.5 py-1 text-xs rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
          >
            {busy === 'accept' ? 'Applying…' : 'Accept'}
          </button>
        </div>
      )}
    </div>
  );
}
