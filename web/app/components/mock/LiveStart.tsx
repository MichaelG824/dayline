'use client';

import { useEffect, useState } from 'react';
import {
  LiveAvailability,
  MockGuideline,
  MockQuestion,
  MockRubric,
  getLiveAvailability,
  getMockGuidelines,
  getMockQuestions,
  getMockRubrics,
  startLiveSession,
} from '../../lib/api';
import { BackButton, CARD, ErrorText, FIELD, Label, PRIMARY_BUTTON, Pill, QUIET_BUTTON } from './ui';

interface Props {
  onCancel: () => void;
  onStarted: (sessionId: string) => void;
}

// Pick a practice repo, then the rubric it will be graded on.
export function LiveStart({ onCancel, onStarted }: Props) {
  const [live, setLive] = useState<LiveAvailability | null>(null);
  const [questions, setQuestions] = useState<MockQuestion[]>([]);
  const [rubrics, setRubrics] = useState<MockRubric[]>([]);
  const [guidelines, setGuidelines] = useState<MockGuideline[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [questionId, setQuestionId] = useState('');
  const [rubricId, setRubricId] = useState('');
  const [guidelineId, setGuidelineId] = useState('');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getLiveAvailability(), getMockQuestions(), getMockRubrics(), getMockGuidelines()])
      .then(([availability, qs, rs, gs]) => {
        setLive(availability);
        setQuestions(qs);
        setRubrics(rs);
        setGuidelines(gs);
        const first = availability.templates[0];
        setTemplateId(first?.id ?? '');
        setRubricId((rs.find((r) => r.roundType === first?.roundType) ?? rs[0])?.id ?? '');
        setGuidelineId(gs[0]?.id ?? '');
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load practice repos.'));
  }, []);

  async function handleStart(e: React.FormEvent) {
    e.preventDefault();
    setStarting(true);
    setError(null);
    try {
      const session = await startLiveSession({
        templateId,
        questionId: questionId || null,
        rubricId: rubricId || null,
        guidelineId: guidelineId || null,
      });
      onStarted(session.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the session.');
      setStarting(false);
    }
  }

  if (!live) {
    return (
      <div className="flex flex-col gap-3 max-w-3xl">
        <BackButton onClick={onCancel}>Practice</BackButton>
        {error ? <ErrorText>{error}</ErrorText> : <p className="font-mono text-sm text-zinc-500">Loading…</p>}
      </div>
    );
  }

  const packOf = (name: string) => live.packs.find((p) => p.name === name);
  const chosenPack = packOf(live.templates.find((t) => t.id === templateId)?.pack ?? '');
  const packBlocker =
    chosenPack && chosenPack.state !== 'ready'
      ? chosenPack.state === 'failed'
        ? `The ${chosenPack.displayName} sandbox image failed to build: ${chosenPack.error}`
        : `The ${chosenPack.displayName} sandbox image is still being built. Try again in a minute.`
      : null;

  return (
    <form onSubmit={handleStart} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onCancel}>Practice</BackButton>
        <h2 className="text-lg font-semibold">Start a live session</h2>
      </div>
      <p className="text-sm text-zinc-500">
        You get a real repo in a sandbox with an editor, a terminal, and its tests. Your saves and test runs are
        recorded, and the session is graded on what you did.
      </p>

      {!live.available && (
        <div className={`${CARD} px-4 py-3 text-sm text-amber-700 dark:text-amber-300`}>{live.reason}</div>
      )}

      <fieldset className="flex flex-col gap-2">
        <legend className="block text-xs font-mono text-zinc-500 mb-1">Practice repo</legend>
        {live.templates.map((t) => {
          const pack = packOf(t.pack);
          const selected = t.id === templateId;
          return (
            <label
              key={t.id}
              className={`${CARD} flex items-start gap-3 px-4 py-3 cursor-pointer ${
                selected ? '!border-indigo-400 dark:!border-indigo-500/70' : 'hover:border-zinc-300 dark:hover:border-zinc-700'
              }`}
            >
              <input
                type="radio"
                name="template"
                checked={selected}
                onChange={() => setTemplateId(t.id)}
                className="mt-1 accent-indigo-500"
              />
              <span className="flex-1 min-w-0 flex flex-col gap-1">
                <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{t.title}</span>
                <span className="text-sm text-zinc-500">{t.summary}</span>
                <span className="flex items-center gap-2 flex-wrap mt-0.5">
                  <Pill>{pack?.displayName ?? t.pack}</Pill>
                  <Pill>{t.roundType}</Pill>
                  <Pill>{t.durationMin} min</Pill>
                </span>
              </span>
            </label>
          );
        })}
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label htmlFor="l-rubric">Rubric</Label>
          <select id="l-rubric" value={rubricId} onChange={(e) => setRubricId(e.target.value)} className={FIELD}>
            <option value="">None (grade later)</option>
            {rubrics.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="l-guideline">Standards</Label>
          <select
            id="l-guideline"
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
        <div>
          <Label htmlFor="l-question">Linked question (optional)</Label>
          <select
            id="l-question"
            value={questionId}
            onChange={(e) => setQuestionId(e.target.value)}
            className={FIELD}
          >
            <option value="">None</option>
            {questions.map((q) => (
              <option key={q.id} value={q.id}>
                {q.company ? `${q.company}: ` : ''}
                {q.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {(error || packBlocker) && <ErrorText>{error ?? packBlocker}</ErrorText>}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={starting || !live.available || !templateId || packBlocker != null}
          className={PRIMARY_BUTTON}
        >
          {starting ? 'Starting the sandbox…' : 'Start'}
        </button>
        <button type="button" onClick={onCancel} className={QUIET_BUTTON}>
          Cancel
        </button>
      </div>
    </form>
  );
}
