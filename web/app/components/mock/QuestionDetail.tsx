'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  MockQuestion,
  MockQuestionDetail,
  deleteMockQuestion,
  getMockQuestion,
  updateMockQuestion,
} from '../../lib/api';
import { languageName, scoreText, sourceLabel } from '../../lib/mock';
import { formatShortDate } from '../../lib/problems';
import { MarkdownView } from '../problems/Markdown';
import {
  BackButton,
  CARD,
  DANGER_BUTTON,
  ErrorText,
  PRIMARY_BUTTON,
  Pill,
  SECONDARY_BUTTON,
  SECTION_TITLE,
} from './ui';

interface Props {
  questionId: string;
  onBack: () => void;
  onOpen: (questionId: string) => void;
  onEdit: (question: MockQuestion) => void;
  onGrade: () => void;
  onOpenSession: (sessionId: string) => void;
}

export function QuestionDetail({ questionId, onBack, onOpen, onEdit, onGrade, onOpenSession }: Props) {
  const [question, setQuestion] = useState<MockQuestionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setQuestion(await getMockQuestion(questionId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load question.');
    }
  }, [questionId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDelete() {
    if (!question || !confirm(`Delete "${question.title}"?`)) return;
    await deleteMockQuestion(question.id);
    onBack();
  }

  async function unlinkCopy(copy: MockQuestion) {
    await updateMockQuestion(copy.id, { canonicalId: null });
    await load();
  }

  if (error && !question) {
    return (
      <div className="flex flex-col gap-3 max-w-3xl">
        <BackButton onClick={onBack}>Question bank</BackButton>
        <ErrorText>{error}</ErrorText>
      </div>
    );
  }
  if (!question) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  // A copy's page points at its canonical question rather than duplicating it.
  const isCopy = question.canonicalId != null;

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <BackButton onClick={onBack}>Question bank</BackButton>

      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">{question.title}</h2>
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={onGrade} className={PRIMARY_BUTTON}>
              Grade a transcript
            </button>
            <button onClick={() => onEdit(question)} className={SECONDARY_BUTTON}>
              Edit
            </button>
            <button onClick={() => void handleDelete()} className={DANGER_BUTTON}>
              Delete
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Pill>{question.roundType}</Pill>
          {question.company && <Pill>{question.company}</Pill>}
          {question.role && <Pill>{question.role}</Pill>}
          {question.languageHint && <Pill>{question.languageHint}</Pill>}
          {question.timesSeen > 1 && (
            <Pill className="!bg-violet-100 dark:!bg-violet-500/20 !text-violet-700 dark:!text-violet-300">
              Reported {question.timesSeen} times
            </Pill>
          )}
        </div>
        <p className="font-mono text-xs text-zinc-500 flex gap-x-5 gap-y-1 flex-wrap">
          <span>{sourceLabel(question.source)}</span>
          {question.reportedOn && <span>Interviewed {formatShortDate(question.reportedOn)}</span>}
          <span>Added {formatShortDate(question.createdAt)}</span>
          {question.sourceUrl && (
            <a
              href={question.sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Open source &#8599;
            </a>
          )}
        </p>
        {isCopy && (
          <p className="text-sm text-zinc-500">
            This is a repeat report.{' '}
            <button
              onClick={() => onOpen(question.canonicalId!)}
              className="text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Open the main question
            </button>
          </p>
        )}
      </div>

      <section>
        <p className={SECTION_TITLE}>PROMPT</p>
        <div className={`${CARD} p-4`}>
          <MarkdownView empty="No prompt written yet.">{question.promptMd}</MarkdownView>
        </div>
      </section>

      {(question.followUps.length > 0 || question.constraints.length > 0) && (
        <div className="grid gap-6 sm:grid-cols-2">
          {question.followUps.length > 0 && (
            <section>
              <p className={SECTION_TITLE}>FOLLOW-UPS</p>
              <ol className="list-decimal pl-5 text-sm flex flex-col gap-1 text-zinc-800 dark:text-zinc-200">
                {question.followUps.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ol>
            </section>
          )}
          {question.constraints.length > 0 && (
            <section>
              <p className={SECTION_TITLE}>CONSTRAINTS</p>
              <ul className="list-disc pl-5 text-sm flex flex-col gap-1 text-zinc-800 dark:text-zinc-200">
                {question.constraints.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {question.notes.trim() && (
        <section>
          <p className={SECTION_TITLE}>MY NOTES</p>
          <p className="text-sm whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">{question.notes}</p>
        </section>
      )}

      {question.copies.length > 0 && (
        <section>
          <p className={SECTION_TITLE}>OTHER REPORTS OF THIS QUESTION</p>
          <div className="flex flex-col gap-2">
            {question.copies.map((copy) => (
              <div key={copy.id} className={`${CARD} flex items-center gap-3 px-4 py-3`}>
                <button onClick={() => onOpen(copy.id)} className="flex-1 min-w-0 text-left">
                  <span className="block truncate text-sm text-zinc-900 dark:text-zinc-100">{copy.title}</span>
                  <span className="block font-mono text-xs text-zinc-500">
                    {sourceLabel(copy.source)}
                    {copy.reportedOn ? ` · ${formatShortDate(copy.reportedOn)}` : ''}
                    {copy.followUps.length > 0 ? ` · ${copy.followUps.length} follow-ups` : ''}
                  </span>
                </button>
                <button
                  onClick={() => void unlinkCopy(copy)}
                  className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
                  title="Not actually the same question"
                >
                  Not the same
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {question.sessions.length > 0 && (
        <section>
          <p className={SECTION_TITLE}>PRACTICE SESSIONS</p>
          <div className="flex flex-col gap-2">
            {question.sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => onOpenSession(s.id)}
                className={`${CARD} flex items-center gap-3 px-4 py-3 text-left hover:border-zinc-300 dark:hover:border-zinc-700`}
              >
                <span className="flex-1 truncate text-sm">{s.title}</span>
                <span className="font-mono text-xs text-zinc-500">{formatShortDate(s.createdAt)}</span>
                <span
                  className={`font-mono text-sm tabular-nums ${s.overallScore != null ? scoreText(s.overallScore) : 'text-zinc-400'}`}
                >
                  {s.overallScore != null ? s.overallScore.toFixed(2) : 'ungraded'}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {question.originalText.trim() && (
        <details className="group">
          <summary className={`${SECTION_TITLE} cursor-pointer select-none list-none`}>
            <span className="group-open:hidden">&rsaquo;</span>
            <span className="hidden group-open:inline">&#8964;</span> ORIGINAL POST
            {question.originalLanguage ? ` (${languageName(question.originalLanguage)})` : ''}
          </summary>
          <pre className={`${CARD} p-4 text-xs whitespace-pre-wrap font-mono text-zinc-600 dark:text-zinc-400`}>
            {question.originalText}
          </pre>
        </details>
      )}
    </div>
  );
}
