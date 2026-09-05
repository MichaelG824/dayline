'use client';

import { useState } from 'react';
import { PlanResponse, Proposal, confirmProposals, sendChatMessage } from '../lib/api';

interface Props {
  day: string;
  onPlanUpdated: (plan: PlanResponse) => void;
}

const SUGGESTIONS = [
  "I'm done with work, redistribute time",
  "How's my progress today?",
  'Add 30 minutes to behavioral',
];

function describeProposal(p: Proposal): string {
  switch (p.type) {
    case 'propose_duration_change':
      return `Set "${p.task_name}" to ${p.new_duration_min} min - ${p.reason}`;
    case 'propose_reprioritization':
      return `Set "${p.task_name}" priority to ${p.new_priority} - ${p.reason}`;
    case 'propose_new_task':
      return `Create "${p.name}" (${p.category}, ${p.est_duration_min} min) - ${p.reason}`;
    default:
      return p.reason;
  }
}

export function ChatTab({ day, onPlanUpdated }: Props) {
  const [message, setMessage] = useState('');
  const [history, setHistory] = useState<unknown[]>([]);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(text: string) {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await sendChatMessage(day, text.trim(), history);
      setExplanation(res.explanation);
      setProposals(res.proposals);
      setSelected(new Set(res.proposals.map((p) => p.id)));
      setHistory(res.history);
      setMessage('');
    } catch {
      setError('Could not reach the chat assistant.');
    } finally {
      setLoading(false);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleApply() {
    const chosen = proposals.filter((p) => selected.has(p.id));
    if (chosen.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const res = await confirmProposals(day, chosen);
      onPlanUpdated(res.plan);
      setProposals([]);
      setExplanation(null);
    } catch {
      setError('Could not apply the selected changes.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-full max-h-[calc(100vh-140px)]">
      <div className="flex-1 overflow-y-auto flex flex-col gap-4">
        <div className="flex gap-3 max-w-2xl">
          <div className="w-8 h-8 shrink-0 rounded-full bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 flex items-center justify-center text-xs font-mono">
            AI
          </div>
          <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-4 text-sm text-zinc-900 dark:text-zinc-100">
            <p className="mb-3">Hi! I can help redistribute time or adjust task allocations.</p>
            <p className="text-zinc-500 mb-1">Try:</p>
            <ul className="list-disc list-inside text-zinc-600 dark:text-zinc-400">
              {SUGGESTIONS.map((s) => (
                <li key={s}>&quot;{s}&quot;</li>
              ))}
            </ul>
          </div>
        </div>

        {explanation && (
          <div className="flex gap-3 max-w-2xl">
            <div className="w-8 h-8 shrink-0 rounded-full bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 flex items-center justify-center text-xs font-mono">
              AI
            </div>
            <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-4 text-sm text-zinc-900 dark:text-zinc-100">
              <p>{explanation}</p>
              {proposals.length > 0 && (
                <div className="mt-3 flex flex-col gap-2">
                  {proposals.map((p) => (
                    <label key={p.id} className="flex items-start gap-2 text-zinc-700 dark:text-zinc-300">
                      <input
                        type="checkbox"
                        checked={selected.has(p.id)}
                        onChange={() => toggle(p.id)}
                        className="mt-1 accent-indigo-500"
                      />
                      <span>{describeProposal(p)}</span>
                    </label>
                  ))}
                  <button
                    onClick={handleApply}
                    disabled={loading || selected.size === 0}
                    className="self-start mt-2 px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
                  >
                    Apply selected
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {error && <p className="text-rose-600 dark:text-rose-400 text-sm">{error}</p>}
      </div>

      <div className="pt-4">
        <div className="flex gap-2 mb-3 flex-wrap">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              disabled={loading}
              className="px-3 py-1.5 text-xs rounded-full border border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 hover:border-zinc-300 dark:hover:border-zinc-700 hover:text-zinc-800 dark:hover:text-zinc-200"
            >
              {s}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(message);
          }}
          className="flex gap-2"
        >
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Message..."
            className="flex-1 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-4 py-2.5 text-sm"
          />
          <button
            type="submit"
            disabled={loading || !message.trim()}
            className="px-5 py-2.5 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
