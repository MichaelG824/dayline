'use client';

import { useEffect, useState } from 'react';
import { MockQuestion, getMockQuestions } from '../../lib/api';
import { ROUND_TYPES, sourceLabel } from '../../lib/mock';
import { CARD, ErrorText, PRIMARY_BUTTON, QUIET_BUTTON, SECONDARY_BUTTON, SELECT, Pill } from './ui';

interface Props {
  onOpen: (questionId: string) => void;
  onNew: () => void;
  onImport: () => void;
}

export function QuestionBank({ onOpen, onNew, onImport }: Props) {
  const [questions, setQuestions] = useState<MockQuestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [roundType, setRoundType] = useState('');
  const [company, setCompany] = useState('');

  useEffect(() => {
    getMockQuestions()
      .then(setQuestions)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load questions.'));
  }, []);

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!questions) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  const companies = [...new Set(questions.map((q) => q.company).filter((c): c is string => !!c))].sort(
    (a, b) => a.localeCompare(b)
  );
  const q = query.trim().toLowerCase();
  const filtered = questions.filter(
    (item) =>
      (!q || item.title.toLowerCase().includes(q) || item.promptMd.toLowerCase().includes(q)) &&
      (!roundType || item.roundType === roundType) &&
      (!company || item.company === company)
  );
  const hasFilters = !!(q || roundType || company);

  return (
    <div className="flex flex-col gap-5 max-w-5xl">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold">Question bank</h2>
          <p className="text-sm text-zinc-500">Private. Reported questions are grouped, so repeats count up.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={onNew} className={SECONDARY_BUTTON}>
            + Question
          </button>
          <button onClick={onImport} className={PRIMARY_BUTTON}>
            Import a post
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search questions..."
          aria-label="Search questions"
          className={`${SELECT} flex-1 min-w-48`}
        />
        <select
          value={roundType}
          onChange={(e) => setRoundType(e.target.value)}
          aria-label="Round type"
          className={SELECT}
        >
          <option value="">All rounds</option>
          {ROUND_TYPES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company" className={SELECT}>
          <option value="">All companies</option>
          {companies.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        {hasFilters && (
          <button
            onClick={() => {
              setQuery('');
              setRoundType('');
              setCompany('');
            }}
            className={QUIET_BUTTON}
          >
            Clear
          </button>
        )}
      </div>

      <div className={`overflow-x-auto ${CARD}`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-200 dark:border-zinc-800 text-left text-xs font-mono text-zinc-500">
              <th className="px-3 py-2 font-normal">Question</th>
              <th className="px-3 py-2 font-normal">Company</th>
              <th className="px-3 py-2 font-normal">Round</th>
              <th className="px-3 py-2 font-normal">Source</th>
              <th className="px-3 py-2 font-normal text-right">Seen</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-10 text-center text-zinc-500">
                  {questions.length === 0
                    ? 'No questions yet. Import a post or add one you were asked.'
                    : 'No questions match these filters.'}
                </td>
              </tr>
            ) : (
              filtered.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => onOpen(item.id)}
                  className="border-b last:border-b-0 border-zinc-100 dark:border-zinc-800/60 hover:bg-zinc-50 dark:hover:bg-zinc-800/30 cursor-pointer"
                >
                  <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">{item.title}</td>
                  <td className="px-3 py-2 text-zinc-600 dark:text-zinc-300">{item.company ?? '-'}</td>
                  <td className="px-3 py-2">
                    <Pill>{item.roundType}</Pill>
                  </td>
                  <td className="px-3 py-2 text-zinc-500">{sourceLabel(item.source)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {item.timesSeen > 1 ? (
                      <span className="text-violet-600 dark:text-violet-400">&times;{item.timesSeen}</span>
                    ) : (
                      <span className="text-zinc-400 dark:text-zinc-600">1</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
