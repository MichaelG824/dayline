// The coding assistant in AI-assisted live sessions. Mirrors
// api/services/mock_assistant.py and api/controllers/mock_assistant.py.

import { apiFetch, checkOk, jsonInit } from './api';

export type AssistantMode = 'ask' | 'plan' | 'edit';

export type ProposalStatus = 'pending' | 'accepted' | 'rejected' | 'conflict';

export interface AssistantProposal {
  id: string;
  path: string;
  summary: string;
  // Unified diff of the file, before -> proposed.
  diff: string;
  added: number;
  removed: number;
  newFile: boolean;
  status: ProposalStatus;
  decidedAt: string | null;
}

export interface AssistantTurn {
  turn: number;
  mode: AssistantMode;
  prompt: string;
  reply: string;
  status: 'running' | 'done' | 'cancelled' | 'error';
  error: string | null;
  // One line per tool call, e.g. "read src/limiter.ts".
  tools: string[];
  durationMs: number | null;
  at: string | null;
  proposals: AssistantProposal[];
}

export interface AssistantState {
  model: string;
  turns: AssistantTurn[];
  // A turn is in flight (e.g. started in another tab).
  running: boolean;
}

export interface AssistantStreamHandlers {
  onStart?: (turnId: string, turn: number) => void;
  onDelta?: (text: string) => void;
  onStatus?: (message: string) => void;
  onTool?: (summary: string) => void;
  onProposal?: (proposal: AssistantProposal) => void;
  // The turn as recorded; also sent (with the message) after an error.
  onDone?: (turn: AssistantTurn) => void;
  onError?: (message: string, turn: AssistantTurn | null) => void;
}

const base = (sessionId: string) => `/api/mock/sessions/${sessionId}/assistant`;

export async function getAssistant(sessionId: string): Promise<AssistantState> {
  const res = await apiFetch(base(sessionId));
  return (await checkOk(res, 'Could not load the assistant')).json();
}

// Send a prompt and read the streamed reply (SSE `data: <json>` frames).
// Aborting `signal` drops the connection; also call cancelAssistantTurn so
// the server stops the model even behind a proxy.
export async function streamAssistantTurn(
  sessionId: string,
  mode: AssistantMode,
  prompt: string,
  handlers: AssistantStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch(`${base(sessionId)}/turns`, { ...jsonInit('POST', { mode, prompt }), signal });
  await checkOk(res, 'The assistant could not reply');
  if (!res.body) throw new Error('The assistant could not reply');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let ended = false;

  const dispatch = (frame: string) => {
    const line = frame.split('\n').find((l) => l.startsWith('data:'));
    if (!line) return;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(line.slice(5).trim());
    } catch {
      return;
    }
    switch (payload.type) {
      case 'start':
        handlers.onStart?.(String(payload.turnId), Number(payload.turn));
        break;
      case 'delta':
        handlers.onDelta?.(String(payload.text ?? ''));
        break;
      case 'status':
        handlers.onStatus?.(String(payload.message ?? ''));
        break;
      case 'tool':
        handlers.onTool?.(String(payload.summary ?? ''));
        break;
      case 'proposal':
        handlers.onProposal?.(payload.proposal as AssistantProposal);
        break;
      case 'done':
        ended = true;
        handlers.onDone?.(payload.turn as AssistantTurn);
        break;
      case 'error':
        ended = true;
        handlers.onError?.(String(payload.message ?? 'The assistant failed'), (payload.turn as AssistantTurn) ?? null);
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
  if (!ended) handlers.onError?.('The connection to the assistant dropped.', null);
}

export async function cancelAssistantTurn(sessionId: string, turnId: string): Promise<void> {
  const res = await apiFetch(`${base(sessionId)}/cancel`, jsonInit('POST', { turnId }));
  await checkOk(res, 'Could not stop the assistant');
}

// Accept writes the proposed file (status "conflict" if it changed since);
// reject writes nothing.
export async function decideAssistantEdit(
  sessionId: string,
  proposalId: string,
  decision: 'accept' | 'reject',
): Promise<AssistantProposal> {
  const res = await apiFetch(`${base(sessionId)}/edits/${proposalId}`, jsonInit('POST', { decision }));
  return (await checkOk(res, decision === 'accept' ? 'Could not apply the edit' : 'Could not reject the edit')).json();
}
