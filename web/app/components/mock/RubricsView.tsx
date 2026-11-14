'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  MockGuideline,
  MockRubric,
  MockRubricInput,
  createMockGuideline,
  createMockRubric,
  deleteMockGuideline,
  deleteMockRubric,
  getMockGuidelines,
  getMockRubrics,
  updateMockGuideline,
  updateMockRubric,
} from '../../lib/api';
import { ROUND_TYPES } from '../../lib/mock';
import { MarkdownField, MarkdownView } from '../problems/Markdown';
import {
  BackButton,
  CARD,
  DANGER_BUTTON,
  ErrorText,
  FIELD,
  Label,
  PRIMARY_BUTTON,
  Pill,
  QUIET_BUTTON,
  SECONDARY_BUTTON,
  SECTION_TITLE,
} from './ui';

type Editing =
  | { kind: 'none' }
  | { kind: 'rubric'; rubric?: MockRubric }
  | { kind: 'guideline'; guideline?: MockGuideline };

export function RubricsView() {
  const [rubrics, setRubrics] = useState<MockRubric[] | null>(null);
  const [guidelines, setGuidelines] = useState<MockGuideline[]>([]);
  const [editing, setEditing] = useState<Editing>({ kind: 'none' });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [rs, gs] = await Promise.all([getMockRubrics(), getMockGuidelines()]);
      setRubrics(rs);
      setGuidelines(gs);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load rubrics.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function done() {
    setEditing({ kind: 'none' });
    void load();
  }

  if (error && !rubrics) return <ErrorText>{error}</ErrorText>;
  if (!rubrics) return <p className="font-mono text-sm text-zinc-500">Loading…</p>;

  if (editing.kind === 'rubric') {
    return <RubricForm rubric={editing.rubric} onDone={done} onCancel={() => setEditing({ kind: 'none' })} />;
  }
  if (editing.kind === 'guideline') {
    return (
      <GuidelineForm guideline={editing.guideline} onDone={done} onCancel={() => setEditing({ kind: 'none' })} />
    );
  }

  return (
    <div className="flex flex-col gap-8 max-w-3xl">
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold">Rubrics</h2>
            <p className="text-sm text-zinc-500">What a round is graded on. Each criterion is scored 1-4.</p>
          </div>
          <button onClick={() => setEditing({ kind: 'rubric' })} className={SECONDARY_BUTTON}>
            + Rubric
          </button>
        </div>
        {rubrics.length === 0 && (
          <div className={`${CARD} px-4 py-8 text-center text-sm text-zinc-500`}>No rubrics yet.</div>
        )}
        {rubrics.map((r) => (
          <div key={r.id} className={`${CARD} p-4 flex flex-col gap-3`}>
            <div className="flex items-center gap-2 flex-wrap">
              <p className="flex-1 min-w-0 font-medium">{r.name}</p>
              {r.roundType && <Pill>{r.roundType}</Pill>}
              <button onClick={() => setEditing({ kind: 'rubric', rubric: r })} className={QUIET_BUTTON}>
                Edit
              </button>
            </div>
            <ul className="flex flex-col gap-1.5 text-sm">
              {r.criteria.map((c) => (
                <li key={c.key} className="flex gap-3">
                  <span className="w-10 shrink-0 font-mono text-xs text-zinc-500 tabular-nums pt-0.5">
                    &times;{c.weight}
                  </span>
                  <span className="min-w-0">
                    <span className="text-zinc-900 dark:text-zinc-100">{c.title}</span>
                    {c.description && <span className="text-zinc-500"> - {c.description}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold">Standards</h2>
            <p className="text-sm text-zinc-500">How strict to be and what good looks like, in your own words.</p>
          </div>
          <button onClick={() => setEditing({ kind: 'guideline' })} className={SECONDARY_BUTTON}>
            + Standards
          </button>
        </div>
        {guidelines.map((g) => (
          <div key={g.id} className={`${CARD} p-4 flex flex-col gap-2`}>
            <div className="flex items-center gap-2">
              <p className="flex-1 min-w-0 font-medium">{g.name}</p>
              <button onClick={() => setEditing({ kind: 'guideline', guideline: g })} className={QUIET_BUTTON}>
                Edit
              </button>
            </div>
            <MarkdownView empty="Empty.">{g.bodyMd}</MarkdownView>
          </div>
        ))}
      </section>
    </div>
  );
}

interface CriterionDraft {
  key?: string;
  title: string;
  description: string;
  weight: string;
}

function RubricForm({
  rubric,
  onDone,
  onCancel,
}: {
  rubric?: MockRubric;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(rubric?.name ?? '');
  const [roundType, setRoundType] = useState(rubric?.roundType ?? '');
  const [criteria, setCriteria] = useState<CriterionDraft[]>(
    rubric?.criteria.map((c) => ({ ...c, weight: String(c.weight) })) ?? [
      { title: '', description: '', weight: '1' },
    ]
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update(index: number, patch: Partial<CriterionDraft>) {
    setCriteria((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= criteria.length) return;
    setCriteria((prev) => {
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const input: MockRubricInput = {
      name,
      roundType: roundType || null,
      criteria: criteria
        .filter((c) => c.title.trim())
        .map((c) => ({
          // Existing keys are kept so older scorecards still line up.
          ...(c.key ? { key: c.key } : {}),
          title: c.title.trim(),
          description: c.description.trim(),
          weight: Number(c.weight),
        })),
    };
    try {
      if (rubric) await updateMockRubric(rubric.id, input);
      else await createMockRubric(input);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save rubric.');
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!rubric || !confirm(`Delete rubric "${rubric.name}"? Existing scorecards are kept.`)) return;
    await deleteMockRubric(rubric.id);
    onDone();
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onCancel}>Rubrics</BackButton>
        <h2 className="text-lg font-semibold">{rubric ? 'Edit rubric' : 'New rubric'}</h2>
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
        <div>
          <Label htmlFor="r-name">Name</Label>
          <input id="r-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
        </div>
        <div>
          <Label htmlFor="r-round">For round</Label>
          <select id="r-round" value={roundType} onChange={(e) => setRoundType(e.target.value)} className={FIELD}>
            <option value="">Any</option>
            {ROUND_TYPES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-[1fr_5rem] gap-2 px-[calc(0.75rem+1px)]">
          <p className={`${SECTION_TITLE} mb-0`}>CRITERIA</p>
          <p className={`${SECTION_TITLE} mb-0`} title="How much this criterion counts in the overall score">
            WEIGHT
          </p>
        </div>
        {criteria.map((c, i) => (
          <div key={i} className={`${CARD} p-3 flex flex-col gap-2`}>
            <div className="grid gap-2 grid-cols-[1fr_5rem]">
              <input
                value={c.title}
                onChange={(e) => update(i, { title: e.target.value })}
                placeholder="Reproduces before fixing"
                aria-label="Criterion title"
                className={FIELD}
              />
              <input
                type="number"
                min={0.1}
                max={10}
                step={0.5}
                value={c.weight}
                onChange={(e) => update(i, { weight: e.target.value })}
                aria-label="Weight"
                title="Weight"
                className={FIELD}
              />
            </div>
            <textarea
              value={c.description}
              onChange={(e) => update(i, { description: e.target.value })}
              rows={2}
              placeholder="What the grader should look for"
              aria-label="Criterion description"
              className={`${FIELD} resize-y`}
            />
            <div className="flex gap-1 text-xs">
              <button type="button" onClick={() => move(i, -1)} disabled={i === 0} className={`${QUIET_BUTTON} !px-2 !py-1 disabled:opacity-30`}>
                &uarr; Up
              </button>
              <button
                type="button"
                onClick={() => move(i, 1)}
                disabled={i === criteria.length - 1}
                className={`${QUIET_BUTTON} !px-2 !py-1 disabled:opacity-30`}
              >
                &darr; Down
              </button>
              <button
                type="button"
                onClick={() => setCriteria((prev) => prev.filter((_, j) => j !== i))}
                className={`${DANGER_BUTTON} !px-2 !py-1 ml-auto`}
              >
                Remove
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setCriteria((prev) => [...prev, { title: '', description: '', weight: '1' }])}
          className={`self-start ${SECONDARY_BUTTON}`}
        >
          + Criterion
        </button>
      </div>

      {error && <ErrorText>{error}</ErrorText>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className={PRIMARY_BUTTON}>
          {saving ? 'Saving…' : 'Save rubric'}
        </button>
        <button type="button" onClick={onCancel} className={QUIET_BUTTON}>
          Cancel
        </button>
        {rubric && (
          <button type="button" onClick={() => void handleDelete()} className={`${DANGER_BUTTON} ml-auto`}>
            Delete
          </button>
        )}
      </div>
    </form>
  );
}

function GuidelineForm({
  guideline,
  onDone,
  onCancel,
}: {
  guideline?: MockGuideline;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(guideline?.name ?? '');
  const [bodyMd, setBodyMd] = useState(guideline?.bodyMd ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (guideline) await updateMockGuideline(guideline.id, { name, bodyMd });
      else await createMockGuideline({ name, bodyMd });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.');
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!guideline || !confirm(`Delete "${guideline.name}"?`)) return;
    await deleteMockGuideline(guideline.id);
    onDone();
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-3xl">
      <div className="flex items-center gap-3">
        <BackButton onClick={onCancel}>Rubrics</BackButton>
        <h2 className="text-lg font-semibold">{guideline ? 'Edit standards' : 'New standards'}</h2>
      </div>
      <div>
        <Label htmlFor="gl-name">Name</Label>
        <input id="gl-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
      </div>
      <div>
        <Label>Standards</Label>
        <MarkdownField
          value={bodyMd}
          onChange={setBodyMd}
          rows={10}
          placeholder="- Score 3 means hire-level for a senior engineer..."
        />
      </div>
      {error && <ErrorText>{error}</ErrorText>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className={PRIMARY_BUTTON}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={onCancel} className={QUIET_BUTTON}>
          Cancel
        </button>
        {guideline && (
          <button type="button" onClick={() => void handleDelete()} className={`${DANGER_BUTTON} ml-auto`}>
            Delete
          </button>
        )}
      </div>
    </form>
  );
}
