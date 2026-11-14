'use client';

import { useState } from 'react';
import { ExtractedQuestion, Extraction, createMockQuestion, extractMockQuestions } from '../../lib/api';
import { QUESTION_SOURCES, ROUND_TYPES, languageName, linesToList, listToLines } from '../../lib/mock';
import {
  BackButton,
  CARD,
  ErrorText,
  FIELD,
  Label,
  PRIMARY_BUTTON,
  QUIET_BUTTON,
  SECONDARY_BUTTON,
  SECTION_TITLE,
} from './ui';

// A suggestion at least this similar starts selected as "same question"; the
// user still confirms by saving.
const PRESELECT_SIMILARITY = 85;

interface Draft {
  title: string;
  roundType: string;
  company: string;
  role: string;
  promptMd: string;
  followUps: string;
  constraints: string;
  languageHint: string;
  reportedOn: string;
  similar: ExtractedQuestion['similar'];
  // '' = a new question; otherwise the id of the question this repeats.
  canonicalId: string;
  state: { kind: 'editing' } | { kind: 'saving' } | { kind: 'saved'; id: string } | { kind: 'skipped' };
  error: string | null;
}

function toDraft(q: ExtractedQuestion): Draft {
  const best = q.similar[0];
  return {
    title: q.title,
    roundType: q.roundType,
    company: q.company ?? '',
    role: q.role ?? '',
    promptMd: q.promptMd,
    followUps: listToLines(q.followUps),
    constraints: listToLines(q.constraints),
    languageHint: q.languageHint ?? '',
    reportedOn: q.reportedOn ?? '',
    similar: q.similar,
    canonicalId: best && best.score >= PRESELECT_SIMILARITY ? best.id : '',
    state: { kind: 'editing' },
    error: null,
  };
}

interface Props {
  onDone: () => void;
  onOpen: (questionId: string) => void;
}

export function ImportPost({ onDone, onOpen }: Props) {
  const [text, setText] = useState('');
  const [source, setSource] = useState('1point3acres');
  const [sourceUrl, setSourceUrl] = useState('');
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);

  async function handleExtract(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) {
      setError('Paste the post first.');
      return;
    }
    setExtracting(true);
    setError(null);
    try {
      const result = await extractMockQuestions(text);
      setExtraction(result);
      setDrafts(result.questions.map(toDraft));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not extract questions.');
    } finally {
      setExtracting(false);
    }
  }

  function update(index: number, patch: Partial<Draft>) {
    setDrafts((prev) => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  async function save(index: number) {
    const d = drafts[index];
    if (!d.title.trim()) {
      update(index, { error: 'Title is required.' });
      return;
    }
    update(index, { state: { kind: 'saving' }, error: null });
    try {
      const saved = await createMockQuestion({
        title: d.title.trim(),
        roundType: d.roundType,
        company: d.company.trim() || null,
        role: d.role.trim() || null,
        promptMd: d.promptMd,
        followUps: linesToList(d.followUps),
        constraints: linesToList(d.constraints),
        languageHint: d.languageHint.trim() || null,
        reportedOn: d.reportedOn || null,
        source,
        sourceUrl: sourceUrl.trim() || null,
        originalText: text,
        originalLanguage: extraction?.originalLanguage ?? null,
        canonicalId: d.canonicalId || null,
      });
      update(index, { state: { kind: 'saved', id: saved.id } });
    } catch (err) {
      update(index, {
        state: { kind: 'editing' },
        error: err instanceof Error ? err.message : 'Could not save.',
      });
    }
  }

  if (!extraction) {
    return (
      <form onSubmit={handleExtract} className="flex flex-col gap-5 max-w-3xl">
        <div className="flex items-center gap-3">
          <BackButton onClick={onDone}>Question bank</BackButton>
          <h2 className="text-lg font-semibold">Import a post</h2>
        </div>
        <p className="text-sm text-zinc-500">
          Paste the interview part of a post. Chinese is fine; questions come back in English. Nothing is
          saved until you review each one.
        </p>
        <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
          <div>
            <Label htmlFor="import-source">Source</Label>
            <select
              id="import-source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className={FIELD}
            >
              {QUESTION_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="import-url">Link (optional)</Label>
            <input
              id="import-url"
              type="url"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://www.1point3acres.com/bbs/thread-..."
              className={FIELD}
            />
          </div>
        </div>
        <div>
          <Label htmlFor="import-text">Post</Label>
          <textarea
            id="import-text"
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={14}
            placeholder="店面: ..."
            className={`${FIELD} resize-y font-mono`}
          />
          <p className="mt-1 text-xs text-zinc-500 font-mono tabular-nums">
            {text.length.toLocaleString()} / 30,000 characters
          </p>
        </div>
        {error && <ErrorText>{error}</ErrorText>}
        <div className="flex items-center gap-3">
          <button type="submit" disabled={extracting || !text.trim()} className={PRIMARY_BUTTON}>
            {extracting ? 'Reading the post…' : 'Extract questions'}
          </button>
          {extracting && <span className="text-xs text-zinc-500">Usually 10-30 seconds.</span>}
        </div>
      </form>
    );
  }

  const remaining = drafts.filter((d) => d.state.kind === 'editing' || d.state.kind === 'saving').length;

  return (
    <div className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={() => setExtraction(null)}>Edit post</BackButton>
        <h2 className="text-lg font-semibold">
          {drafts.length} question{drafts.length === 1 ? '' : 's'} found
          {extraction.originalLanguage && extraction.originalLanguage !== 'en' && (
            <span className="font-normal text-zinc-500">
              {' '}
              · translated from {languageName(extraction.originalLanguage)}
            </span>
          )}
        </h2>
      </div>

      {drafts.map((d, i) => (
        <DraftCard
          key={i}
          draft={d}
          onChange={(patch) => update(i, patch)}
          onSave={() => void save(i)}
          onSkip={() => update(i, { state: { kind: 'skipped' } })}
          onOpen={onOpen}
        />
      ))}

      <div className="flex items-center gap-3">
        <button onClick={onDone} className={remaining === 0 ? PRIMARY_BUTTON : SECONDARY_BUTTON}>
          {remaining === 0 ? 'Done' : `Finish (${remaining} not saved)`}
        </button>
      </div>
    </div>
  );
}

function DraftCard({
  draft,
  onChange,
  onSave,
  onSkip,
  onOpen,
}: {
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
  onSave: () => void;
  onSkip: () => void;
  onOpen: (questionId: string) => void;
}) {
  const { state } = draft;
  if (state.kind === 'saved' || state.kind === 'skipped') {
    return (
      <div className={`${CARD} flex items-center gap-3 px-4 py-3 opacity-80`}>
        <span
          className={`font-mono text-xs ${state.kind === 'saved' ? 'text-emerald-600 dark:text-emerald-400' : 'text-zinc-500'}`}
        >
          {state.kind === 'saved' ? (draft.canonicalId ? 'SAVED AS REPEAT' : 'SAVED') : 'SKIPPED'}
        </span>
        <span className="flex-1 truncate text-sm">{draft.title}</span>
        {state.kind === 'saved' ? (
          <button
            onClick={() => onOpen(state.id)}
            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            Open
          </button>
        ) : (
          <button onClick={() => onChange({ state: { kind: 'editing' } })} className={QUIET_BUTTON}>
            Undo
          </button>
        )}
      </div>
    );
  }

  const saving = state.kind === 'saving';
  return (
    <div className={`${CARD} p-4 flex flex-col gap-4`}>
      <div className="grid gap-3 sm:grid-cols-[1fr_13rem]">
        <div>
          <Label>Title</Label>
          <input value={draft.title} onChange={(e) => onChange({ title: e.target.value })} className={FIELD} />
        </div>
        <div>
          <Label>Round</Label>
          <select
            value={draft.roundType}
            onChange={(e) => onChange({ roundType: e.target.value })}
            className={FIELD}
          >
            {ROUND_TYPES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label>Company</Label>
          <input value={draft.company} onChange={(e) => onChange({ company: e.target.value })} className={FIELD} />
        </div>
        <div>
          <Label>Role</Label>
          <input value={draft.role} onChange={(e) => onChange({ role: e.target.value })} className={FIELD} />
        </div>
        <div>
          <Label>Interview date</Label>
          <input
            type="date"
            value={draft.reportedOn}
            onChange={(e) => onChange({ reportedOn: e.target.value })}
            className={FIELD}
          />
        </div>
      </div>
      <div>
        <Label>Prompt</Label>
        <textarea
          value={draft.promptMd}
          onChange={(e) => onChange({ promptMd: e.target.value })}
          rows={6}
          className={`${FIELD} resize-y font-mono`}
        />
      </div>
      <div>
        <Label>Follow-ups (one per line)</Label>
        <textarea
          value={draft.followUps}
          onChange={(e) => onChange({ followUps: e.target.value })}
          rows={3}
          className={`${FIELD} resize-y`}
        />
      </div>

      <fieldset>
        <legend className={SECTION_TITLE}>IS THIS ALREADY IN THE BANK?</legend>
        <div className="flex flex-col gap-1.5 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              checked={draft.canonicalId === ''}
              onChange={() => onChange({ canonicalId: '' })}
              className="accent-indigo-500"
            />
            New question
          </label>
          {draft.similar.map((s) => (
            <label key={s.id} className="flex items-center gap-2">
              <input
                type="radio"
                checked={draft.canonicalId === s.id}
                onChange={() => onChange({ canonicalId: s.id })}
                className="accent-indigo-500"
              />
              <span className="min-w-0 truncate">
                Same as <span className="font-medium">{s.title}</span>
                {s.company ? <span className="text-zinc-500"> ({s.company})</span> : null}
              </span>
              <span className="ml-auto shrink-0 font-mono text-xs tabular-nums text-zinc-500">
                {Math.round(s.score)}% similar
              </span>
            </label>
          ))}
          {draft.similar.length === 0 && (
            <p className="text-xs text-zinc-500">No similar questions in the bank.</p>
          )}
        </div>
      </fieldset>

      {draft.error && <ErrorText>{draft.error}</ErrorText>}
      <div className="flex gap-2">
        <button onClick={onSave} disabled={saving} className={PRIMARY_BUTTON}>
          {saving ? 'Saving…' : draft.canonicalId ? 'Save as repeat' : 'Save'}
        </button>
        <button onClick={onSkip} disabled={saving} className={QUIET_BUTTON}>
          Skip
        </button>
      </div>
    </div>
  );
}
