'use client';

import { useEffect, useState } from 'react';
import {
  MockGuideline,
  MockQuestion,
  MockRubric,
  createMockSession,
  getMockGuidelines,
  getMockQuestions,
  getMockRubrics,
  gradeMockSession,
} from '../../lib/api';
import { BackButton, ErrorText, FIELD, Label, PRIMARY_BUTTON, QUIET_BUTTON } from './ui';

interface Props {
  initialQuestionId?: string;
  onCancel: () => void;
  onCreated: (sessionId: string) => void;
}

const TRANSCRIPT_PLACEHOLDER = `Any format works. Speaker labels and timestamps help the grader cite evidence:

[00:01] Interviewer: The checkout endpoint lets two people borrow the same book.
[00:02] Me: Let me run the tests first to see what fails.`;

export function NewGrading({ initialQuestionId, onCancel, onCreated }: Props) {
  const [questions, setQuestions] = useState<MockQuestion[]>([]);
  const [rubrics, setRubrics] = useState<MockRubric[]>([]);
  const [guidelines, setGuidelines] = useState<MockGuideline[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [title, setTitle] = useState('');
  const [questionId, setQuestionId] = useState(initialQuestionId ?? '');
  const [rubricId, setRubricId] = useState('');
  const [guidelineId, setGuidelineId] = useState('');
  const [transcript, setTranscript] = useState('');
  const [phase, setPhase] = useState<'idle' | 'saving' | 'grading'>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getMockQuestions(), getMockRubrics(), getMockGuidelines()])
      .then(([qs, rs, gs]) => {
        setQuestions(qs);
        setRubrics(rs);
        setGuidelines(gs);
        // Default to the rubric made for this question's round type, if any.
        const round = qs.find((q) => q.id === initialQuestionId)?.roundType;
        setRubricId((rs.find((r) => r.roundType === round) ?? rs[0])?.id ?? '');
        setGuidelineId(gs[0]?.id ?? '');
        setLoaded(true);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load the form.'));
  }, [initialQuestionId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!transcript.trim()) {
      setError('Paste a transcript first.');
      return;
    }
    if (!rubricId) {
      setError('Create a rubric first (Rubrics & standards).');
      return;
    }
    setError(null);
    setPhase('saving');
    let sessionId: string | null = null;
    try {
      const question = questions.find((q) => q.id === questionId);
      const session = await createMockSession({
        title: title.trim() || question?.title || 'Pasted transcript',
        transcript,
        questionId: questionId || null,
        rubricId,
        guidelineId: guidelineId || null,
      });
      sessionId = session.id;
      setPhase('grading');
      await gradeMockSession(session.id);
      onCreated(session.id);
    } catch (err) {
      // A saved-but-ungraded session is still useful: open it so grading can be retried.
      if (sessionId) {
        onCreated(sessionId);
        return;
      }
      setError(err instanceof Error ? err.message : 'Could not grade.');
      setPhase('idle');
    }
  }

  const busy = phase !== 'idle';

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onCancel}>Grading</BackButton>
        <h2 className="text-lg font-semibold">Grade a transcript</h2>
      </div>

      <div>
        <Label htmlFor="g-title">Title</Label>
        <input
          id="g-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Defaults to the question title"
          className={FIELD}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label htmlFor="g-question">Question (optional)</Label>
          <select
            id="g-question"
            value={questionId}
            onChange={(e) => setQuestionId(e.target.value)}
            disabled={!loaded}
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
        <div>
          <Label htmlFor="g-rubric">Rubric</Label>
          <select
            id="g-rubric"
            value={rubricId}
            onChange={(e) => setRubricId(e.target.value)}
            disabled={!loaded}
            className={FIELD}
          >
            {rubrics.length === 0 && <option value="">No rubrics yet</option>}
            {rubrics.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="g-guideline">Standards</Label>
          <select
            id="g-guideline"
            value={guidelineId}
            onChange={(e) => setGuidelineId(e.target.value)}
            disabled={!loaded}
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
      </div>

      <div>
        <Label htmlFor="g-transcript">Transcript</Label>
        <textarea
          id="g-transcript"
          autoFocus
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          rows={16}
          placeholder={TRANSCRIPT_PLACEHOLDER}
          className={`${FIELD} resize-y font-mono`}
        />
      </div>

      {error && <ErrorText>{error}</ErrorText>}

      <div className="flex items-center gap-3">
        <button type="submit" disabled={busy || !loaded} className={PRIMARY_BUTTON}>
          {phase === 'saving' ? 'Saving…' : phase === 'grading' ? 'Grading…' : 'Grade'}
        </button>
        {phase === 'grading' ? (
          <span className="text-xs text-zinc-500">Reading the whole transcript. Usually under a minute.</span>
        ) : (
          <button type="button" onClick={onCancel} className={QUIET_BUTTON}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
