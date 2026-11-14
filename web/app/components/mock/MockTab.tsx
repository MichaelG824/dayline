'use client';

import { useState } from 'react';
import { MockQuestion, MockSessionSummary } from '../../lib/api';
import { ImportPost } from './ImportPost';
import { LiveStart } from './LiveStart';
import { NewGrading } from './NewGrading';
import { QuestionBank } from './QuestionBank';
import { QuestionDetail } from './QuestionDetail';
import { QuestionForm } from './QuestionForm';
import { RubricsView } from './RubricsView';
import { SessionList } from './SessionList';
import { SessionView } from './SessionView';
import { Workspace } from './Workspace';

type Section = 'questions' | 'practice' | 'rubrics';

// Which screen of the tab is showing. Kept here (not in each section) so a
// question can jump straight to "grade a transcript for this question" and a
// session can link back to its question.
type View =
  | { kind: 'questions' }
  | { kind: 'question'; id: string }
  | { kind: 'question-form'; question?: MockQuestion }
  | { kind: 'import' }
  | { kind: 'sessions' }
  | { kind: 'new-grading'; questionId?: string }
  | { kind: 'new-live' }
  | { kind: 'workspace'; id: string }
  | { kind: 'session'; id: string }
  | { kind: 'rubrics' };

const SECTIONS: { id: Section; label: string; home: View }[] = [
  { id: 'questions', label: 'Question bank', home: { kind: 'questions' } },
  { id: 'practice', label: 'Practice', home: { kind: 'sessions' } },
  { id: 'rubrics', label: 'Rubrics & standards', home: { kind: 'rubrics' } },
];

function sectionOf(view: View): Section {
  if (view.kind === 'rubrics') return 'rubrics';
  if (['sessions', 'new-grading', 'new-live', 'workspace', 'session'].includes(view.kind)) {
    return 'practice';
  }
  return 'questions';
}

interface Props {
  day: string;
  onTasksChanged: () => void;
}

export function MockTab({ day, onTasksChanged }: Props) {
  const [view, setView] = useState<View>({ kind: 'questions' });
  const section = sectionOf(view);

  // A live session still in progress opens its workspace; anything else its record.
  const openSession = (s: Pick<MockSessionSummary, 'id' | 'kind' | 'status'>) =>
    setView(
      s.kind === 'live' && s.status === 'live'
        ? { kind: 'workspace', id: s.id }
        : { kind: 'session', id: s.id },
    );

  return (
    <div className="flex flex-col gap-6">
      <nav className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800 -mt-2">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setView(s.home)}
            className={`px-3 py-2 text-sm -mb-px border-b-2 transition-colors ${
              section === s.id
                ? 'border-indigo-500 text-zinc-900 dark:text-zinc-100'
                : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
            }`}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {view.kind === 'questions' && (
        <QuestionBank
          onOpen={(id) => setView({ kind: 'question', id })}
          onNew={() => setView({ kind: 'question-form' })}
          onImport={() => setView({ kind: 'import' })}
        />
      )}
      {view.kind === 'question' && (
        <QuestionDetail
          key={view.id}
          questionId={view.id}
          onBack={() => setView({ kind: 'questions' })}
          onOpen={(id) => setView({ kind: 'question', id })}
          onEdit={(question) => setView({ kind: 'question-form', question })}
          onGrade={() => setView({ kind: 'new-grading', questionId: view.id })}
          onOpenSession={(id) => setView({ kind: 'session', id })}
        />
      )}
      {view.kind === 'question-form' && (
        <QuestionForm
          question={view.question}
          onCancel={() =>
            setView(view.question ? { kind: 'question', id: view.question.id } : { kind: 'questions' })
          }
          onSaved={(saved) => setView({ kind: 'question', id: saved.id })}
        />
      )}
      {view.kind === 'import' && (
        <ImportPost
          onDone={() => setView({ kind: 'questions' })}
          onOpen={(id) => setView({ kind: 'question', id })}
        />
      )}
      {view.kind === 'sessions' && (
        <SessionList
          onOpen={openSession}
          onNewLive={() => setView({ kind: 'new-live' })}
          onNewGrading={() => setView({ kind: 'new-grading' })}
        />
      )}
      {view.kind === 'new-grading' && (
        <NewGrading
          initialQuestionId={view.questionId}
          onCancel={() => setView({ kind: 'sessions' })}
          onCreated={(id) => setView({ kind: 'session', id })}
        />
      )}
      {view.kind === 'new-live' && (
        <LiveStart
          onCancel={() => setView({ kind: 'sessions' })}
          onStarted={(id) => setView({ kind: 'workspace', id })}
        />
      )}
      {view.kind === 'workspace' && (
        <Workspace
          key={view.id}
          sessionId={view.id}
          onExit={() => setView({ kind: 'sessions' })}
          onEnded={(id) => setView({ kind: 'session', id })}
        />
      )}
      {view.kind === 'session' && (
        <SessionView
          key={view.id}
          sessionId={view.id}
          day={day}
          onBack={() => setView({ kind: 'sessions' })}
          onOpenWorkspace={() => setView({ kind: 'workspace', id: view.id })}
          onOpenQuestion={(id) => setView({ kind: 'question', id })}
          onDeleted={() => setView({ kind: 'sessions' })}
          onTasksChanged={onTasksChanged}
        />
      )}
      {view.kind === 'rubrics' && <RubricsView />}
    </div>
  );
}
