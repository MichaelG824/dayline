'use client';

import { useEffect, useRef, useState } from 'react';
import { ChatMessage, StageStatus, StagedRound, StagedStage } from '../../lib/api';
import { formatClock } from '../../lib/mock';
import { MarkdownView } from '../problems/Markdown';
import { GraderText } from './GraderText';

const STATUS_DOT: Record<StageStatus, string> = {
  passed: 'bg-emerald-500 text-white',
  skipped: 'bg-amber-500 text-white',
  failed: 'bg-rose-500 text-white',
  active: 'bg-indigo-500 text-white ring-4 ring-indigo-500/15',
  locked: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500',
};

const STATUS_MARK: Record<StageStatus, string> = {
  passed: '✓',
  skipped: '–',
  failed: '✗',
  active: '',
  locked: '',
};

export const STAGE_STATUS_LABEL: Record<StageStatus, string> = {
  passed: 'Passed',
  skipped: 'Skipped',
  failed: 'Not passed',
  active: 'In progress',
  locked: 'Locked',
};

interface Props {
  staged: StagedRound;
  now: number;
  // The interviewer is writing a reply.
  thinking: boolean;
  chatError: string | null;
  skipping: 'idle' | 'confirm' | 'skipping';
  finishing: boolean;
  onSend: (text: string) => void;
  onFollowUp: () => void;
  onRetry: () => void;
  onSkip: () => void;
  onFinish: () => void;
  onClose: () => void;
}

// The staged round's side panel: stage progress, the active stage's prompt,
// and the interviewer chat.
export function StagePanel({
  staged,
  now,
  thinking,
  chatError,
  skipping,
  finishing,
  onSend,
  onFollowUp,
  onRetry,
  onSkip,
  onFinish,
  onClose,
}: Props) {
  const active = staged.activeStage != null ? staged.stages[staged.activeStage - 1] : null;
  const [promptOpen, setPromptOpen] = useState(true);
  // A new stage's prompt always opens.
  useEffect(() => setPromptOpen(true), [staged.activeStage]);
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="shrink-0 px-4 pt-3 pb-2.5 border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-3 mb-1.5">
          <p className="font-mono text-xs tracking-widest text-zinc-500">STAGES</p>
          {active && (
            <button
              onClick={onSkip}
              disabled={skipping === 'skipping'}
              className={`ml-auto text-xs disabled:opacity-40 ${
                skipping === 'confirm'
                  ? 'text-rose-600 dark:text-rose-400 font-medium'
                  : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'
              }`}
              title="Move on without passing this stage. It is recorded as skipped."
            >
              {skipping === 'skipping' ? 'Skipping…' : skipping === 'confirm' ? 'Confirm skip' : 'Skip stage'}
            </button>
          )}
          <button
            onClick={onClose}
            className={`lg:hidden ${active ? '' : 'ml-auto'} -mr-1 px-1 text-lg leading-none text-zinc-400 hover:text-zinc-900 dark:hover:text-white`}
            aria-label="Close the stage panel"
          >
            &times;
          </button>
        </div>
        <ol className="flex flex-col gap-0.5">
          {staged.stages.map((stage) => (
            <StageRow key={stage.number} stage={stage} now={now} />
          ))}
        </ol>
      </div>

      {active ? (
        <div className="shrink-0 max-h-[40%] flex flex-col border-b border-zinc-200 dark:border-zinc-800">
          <button
            onClick={() => setPromptOpen((open) => !open)}
            className="shrink-0 flex items-center gap-2 px-4 pt-3 pb-2 text-left"
            aria-expanded={promptOpen}
          >
            <span className="font-mono text-xs tracking-widest text-zinc-500">PROMPT</span>
            <span className="ml-auto text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
              {promptOpen ? 'Hide' : 'Show'}
            </span>
          </button>
          {promptOpen && (
            <div className="min-h-0 overflow-y-auto px-4 pb-3">
              <MarkdownView>{active.promptMd ?? ''}</MarkdownView>
            </div>
          )}
        </div>
      ) : (
        <div className="shrink-0 px-4 py-4 border-b border-zinc-200 dark:border-zinc-800 flex flex-col gap-3">
          <p className="text-sm font-medium">Every stage is done</p>
          <p className="text-sm text-zinc-500">
            Finish the round to save your code and see the stage-by-stage summary. You can grade it from there.
          </p>
          <button
            onClick={onFinish}
            disabled={finishing}
            className="self-start px-3 py-1.5 text-sm rounded-md bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
          >
            {finishing ? 'Finishing…' : 'Finish round'}
          </button>
        </div>
      )}

      <Chat
        messages={staged.chat}
        thinking={thinking}
        error={chatError}
        canAsk={active != null}
        onSend={onSend}
        onFollowUp={onFollowUp}
        onRetry={onRetry}
      />
    </div>
  );
}

function StageRow({ stage, now }: { stage: StagedStage; now: number }) {
  const locked = stage.status === 'locked';
  const active = stage.status === 'active';
  const spent =
    active && stage.startedAt ? (now - Date.parse(stage.startedAt)) / 1000 : stage.timeSpentS;
  const over = active && stage.targetMin != null && spent != null && spent > stage.targetMin * 60;
  return (
    <li
      className={`flex items-center gap-2.5 rounded-md px-2 py-1 -mx-2 text-sm ${
        active ? 'bg-indigo-50 dark:bg-indigo-500/10' : ''
      }`}
    >
      <span
        className={`w-5 h-5 shrink-0 rounded-full flex items-center justify-center text-[0.65rem] font-mono font-semibold ${
          STATUS_DOT[stage.status]
        }`}
        aria-hidden
      >
        {STATUS_MARK[stage.status] || stage.number}
      </span>
      <span
        className={`flex-1 min-w-0 truncate ${
          locked
            ? 'text-zinc-400 dark:text-zinc-500'
            : active
              ? 'font-medium text-zinc-900 dark:text-zinc-100'
              : 'text-zinc-700 dark:text-zinc-300'
        }`}
        title={stage.title ?? undefined}
      >
        {stage.title ?? `Stage ${stage.number}`}
        <span className="sr-only"> ({STAGE_STATUS_LABEL[stage.status]})</span>
      </span>
      {locked ? (
        <LockIcon />
      ) : (
        spent != null && (
          <span
            className={`shrink-0 font-mono text-xs tabular-nums ${
              over ? 'text-amber-600 dark:text-amber-400' : 'text-zinc-400 dark:text-zinc-500'
            }`}
            title={stage.targetMin ? `Suggested: ${stage.targetMin} min` : undefined}
          >
            {formatClock(spent)}
          </span>
        )
      )}
    </li>
  );
}

function LockIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      className="w-3.5 h-3.5 shrink-0 text-zinc-300 dark:text-zinc-600"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
    >
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  );
}

function Chat({
  messages,
  thinking,
  error,
  canAsk,
  onSend,
  onFollowUp,
  onRetry,
}: {
  messages: ChatMessage[];
  thinking: boolean;
  error: string | null;
  canAsk: boolean;
  onSend: (text: string) => void;
  onFollowUp: () => void;
  onRetry: () => void;
}) {
  const [draft, setDraft] = useState('');
  const scroller = useRef<HTMLDivElement>(null);

  // Keep the newest message in view.
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, thinking, error]);

  function send() {
    const text = draft.trim();
    if (!text || thinking) return;
    onSend(text);
    setDraft('');
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex items-center gap-2 px-4 pt-3 pb-2 shrink-0">
        <p className="font-mono text-xs tracking-widest text-zinc-500">INTERVIEWER</p>
        {canAsk && (
          <button
            onClick={onFollowUp}
            disabled={thinking}
            className="ml-auto text-xs text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-40 disabled:no-underline"
          >
            Ask for a follow-up
          </button>
        )}
      </div>
      <div ref={scroller} className="flex-1 min-h-0 overflow-y-auto px-4 pb-3 flex flex-col gap-3">
        {messages.length === 0 && !thinking && !error && (
          <p className="text-sm text-zinc-500">The interviewer will be with you in a moment.</p>
        )}
        {messages.map((m, i) => (
          <Message key={i} message={m} />
        ))}
        {thinking && (
          <p className="text-xs text-zinc-500 flex items-center gap-2">
            <span className="flex gap-0.5" aria-hidden>
              {[0, 150, 300].map((delay) => (
                <span
                  key={delay}
                  className="w-1 h-1 rounded-full bg-zinc-400 animate-pulse"
                  style={{ animationDelay: `${delay}ms` }}
                />
              ))}
            </span>
            The interviewer is reading your code…
          </p>
        )}
        {error && !thinking && (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            {error}{' '}
            <button onClick={onRetry} className="text-indigo-600 dark:text-indigo-400 hover:underline">
              Try again
            </button>
          </p>
        )}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="shrink-0 flex items-end gap-2 px-3 py-3 border-t border-zinc-200 dark:border-zinc-800"
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
          placeholder="Explain your approach, or ask a question…"
          aria-label="Message the interviewer"
          className="flex-1 min-w-0 resize-none bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm leading-snug"
        />
        <button
          type="submit"
          disabled={!draft.trim() || thinking}
          className="px-3 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}

function Message({ message }: { message: ChatMessage }) {
  if (message.role === 'candidate') {
    return (
      <div className="self-end max-w-[85%] rounded-xl rounded-br-sm bg-indigo-500 text-white px-3 py-2 text-sm whitespace-pre-wrap break-words">
        {message.text}
      </div>
    );
  }
  return (
    <div className="flex gap-2.5 max-w-[95%]">
      <span
        className="w-6 h-6 shrink-0 rounded-full bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 flex items-center justify-center text-[0.65rem] font-mono"
        aria-hidden
      >
        IN
      </span>
      <p className="min-w-0 text-sm leading-relaxed text-zinc-800 dark:text-zinc-200 whitespace-pre-wrap break-words">
        <GraderText text={message.text} />
      </p>
    </div>
  );
}
