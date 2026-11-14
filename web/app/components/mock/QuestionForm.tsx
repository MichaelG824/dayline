'use client';

import { useState } from 'react';
import { MockQuestion, MockQuestionInput, createMockQuestion, updateMockQuestion } from '../../lib/api';
import { QUESTION_SOURCES, ROUND_TYPES, linesToList, listToLines } from '../../lib/mock';
import { MarkdownField } from '../problems/Markdown';
import { BackButton, ErrorText, FIELD, Label, PRIMARY_BUTTON, QUIET_BUTTON } from './ui';

interface Props {
  question?: MockQuestion;
  onSaved: (question: MockQuestion) => void;
  onCancel: () => void;
}

export function QuestionForm({ question, onSaved, onCancel }: Props) {
  const [title, setTitle] = useState(question?.title ?? '');
  const [roundType, setRoundType] = useState(question?.roundType ?? 'AI-assisted project');
  const [company, setCompany] = useState(question?.company ?? '');
  const [role, setRole] = useState(question?.role ?? '');
  const [source, setSource] = useState(question?.source ?? 'own');
  const [sourceUrl, setSourceUrl] = useState(question?.sourceUrl ?? '');
  const [reportedOn, setReportedOn] = useState(question?.reportedOn ?? '');
  const [languageHint, setLanguageHint] = useState(question?.languageHint ?? '');
  const [promptMd, setPromptMd] = useState(question?.promptMd ?? '');
  const [constraints, setConstraints] = useState(listToLines(question?.constraints ?? []));
  const [followUps, setFollowUps] = useState(listToLines(question?.followUps ?? []));
  const [notes, setNotes] = useState(question?.notes ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setError('Title is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const input: MockQuestionInput = {
      title: title.trim(),
      roundType,
      company: company.trim() || null,
      role: role.trim() || null,
      source,
      sourceUrl: sourceUrl.trim() || null,
      reportedOn: reportedOn || null,
      languageHint: languageHint.trim() || null,
      promptMd,
      constraints: linesToList(constraints),
      followUps: linesToList(followUps),
      notes,
    };
    try {
      onSaved(question ? await updateMockQuestion(question.id, input) : await createMockQuestion(input));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save question.');
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onCancel}>Back</BackButton>
        <h2 className="text-lg font-semibold">{question ? 'Edit question' : 'Add question'}</h2>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
        <div>
          <Label htmlFor="q-title">Title</Label>
          <input
            id="q-title"
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Fix the library checkout bug, then add late fees"
            className={FIELD}
          />
        </div>
        <div>
          <Label htmlFor="q-round">Round</Label>
          <select id="q-round" value={roundType} onChange={(e) => setRoundType(e.target.value)} className={FIELD}>
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
          <Label htmlFor="q-company">Company</Label>
          <input id="q-company" value={company} onChange={(e) => setCompany(e.target.value)} className={FIELD} />
        </div>
        <div>
          <Label htmlFor="q-role">Role</Label>
          <input
            id="q-role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            placeholder="Senior SWE"
            className={FIELD}
          />
        </div>
        <div>
          <Label htmlFor="q-lang">Language</Label>
          <input
            id="q-lang"
            value={languageHint}
            onChange={(e) => setLanguageHint(e.target.value)}
            placeholder="python"
            className={FIELD}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-[12rem_1fr_11rem]">
        <div>
          <Label htmlFor="q-source">Source</Label>
          <select id="q-source" value={source} onChange={(e) => setSource(e.target.value)} className={FIELD}>
            {QUESTION_SOURCES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="q-url">Source link</Label>
          <input
            id="q-url"
            type="url"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://www.1point3acres.com/bbs/thread-..."
            className={FIELD}
          />
        </div>
        <div>
          <Label htmlFor="q-date">Interview date</Label>
          <input
            id="q-date"
            type="date"
            value={reportedOn}
            onChange={(e) => setReportedOn(e.target.value)}
            className={FIELD}
          />
        </div>
      </div>

      <div>
        <Label>Prompt</Label>
        <MarkdownField
          value={promptMd}
          onChange={setPromptMd}
          rows={10}
          placeholder="The question as the interviewer stated it, with any starting setup or examples."
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="q-followups">Follow-up questions (one per line)</Label>
          <textarea
            id="q-followups"
            value={followUps}
            onChange={(e) => setFollowUps(e.target.value)}
            rows={5}
            placeholder="What if two requests arrive at the same time?"
            className={`${FIELD} resize-y`}
          />
        </div>
        <div>
          <Label htmlFor="q-constraints">Constraints (one per line)</Label>
          <textarea
            id="q-constraints"
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            rows={5}
            placeholder={'45 minutes\nAI assistant allowed'}
            className={`${FIELD} resize-y`}
          />
        </div>
      </div>

      <div>
        <Label htmlFor="q-notes">My notes</Label>
        <textarea
          id="q-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className={`${FIELD} resize-y`}
        />
      </div>

      {error && <ErrorText>{error}</ErrorText>}

      <div className="flex gap-2">
        <button type="submit" disabled={submitting} className={PRIMARY_BUTTON}>
          {submitting ? 'Saving…' : question ? 'Save changes' : 'Add question'}
        </button>
        <button type="button" onClick={onCancel} className={QUIET_BUTTON}>
          Cancel
        </button>
      </div>
    </form>
  );
}
