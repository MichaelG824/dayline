'use client';

import { TestCase, TestReport } from '../../lib/api';

const STATUS_TEXT: Record<TestReport['status'], { label: string; className: string }> = {
  passed: { label: 'All tests pass', className: 'text-emerald-600 dark:text-emerald-400' },
  failed: { label: 'Some tests fail', className: 'text-rose-600 dark:text-rose-400' },
  error: { label: 'The tests could not run', className: 'text-amber-600 dark:text-amber-400' },
  timeout: { label: 'The tests timed out', className: 'text-amber-600 dark:text-amber-400' },
};

const OUTCOME_MARK: Record<TestCase['outcome'], { mark: string; className: string }> = {
  passed: { mark: '✓', className: 'text-emerald-600 dark:text-emerald-400' },
  failed: { mark: '✗', className: 'text-rose-600 dark:text-rose-400' },
  error: { mark: '!', className: 'text-amber-600 dark:text-amber-400' },
  skipped: { mark: '–', className: 'text-zinc-400' },
};

export function reportCounts(report: TestReport): string {
  const parts = [`${report.passed} passed`];
  if (report.failed) parts.push(`${report.failed} failed`);
  if (report.errors) parts.push(`${report.errors} errors`);
  if (report.skipped) parts.push(`${report.skipped} skipped`);
  return parts.join(' · ');
}

// Where a test lives, shortly: pytest classnames are dotted module paths
// (tests.test_checkout -> test_checkout); vitest's are file paths
// (src/limiter.test.ts -> limiter.test.ts).
export function caseWhere(classname: string): string {
  if (classname.includes('/') || /\.[cm]?[jt]sx?$/.test(classname)) {
    return classname.split('/').pop() ?? classname;
  }
  return classname.split('.').pop() ?? classname;
}

function caseName(c: TestCase): string {
  const where = caseWhere(c.classname);
  return where && where !== c.name ? `${where} › ${c.name}` : c.name;
}

// The last test run: headline, failures with their messages, then passes.
// Raw output stays one click away for anything the parsed cases miss.
export function TestResults({
  report,
  running,
  empty = 'Run the tests to see results here.',
}: {
  report: TestReport | null;
  running: boolean;
  empty?: string;
}) {
  if (!report) {
    return <p className="p-4 text-sm text-zinc-500">{running ? 'Running the tests…' : empty}</p>;
  }
  const status = STATUS_TEXT[report.status];
  const problems = report.cases.filter((c) => c.outcome === 'failed' || c.outcome === 'error');
  const others = report.cases.filter((c) => c.outcome === 'passed' || c.outcome === 'skipped');

  return (
    <div className={`p-4 flex flex-col gap-3 ${running ? 'opacity-50' : ''}`}>
      <div className="flex items-baseline gap-3 flex-wrap">
        <p className={`text-sm font-medium ${status.className}`}>{status.label}</p>
        <p className="font-mono text-xs text-zinc-500 tabular-nums">
          {reportCounts(report)} · {report.duration_s.toFixed(1)}s
        </p>
      </div>

      {problems.map((c, i) => (
        <div key={`${c.classname}-${c.name}-${i}`} className="flex flex-col gap-1">
          <p className="text-sm font-mono">
            <span className={OUTCOME_MARK[c.outcome].className}>{OUTCOME_MARK[c.outcome].mark}</span>{' '}
            {caseName(c)}
          </p>
          {c.message && (
            <pre className="overflow-x-auto rounded-md bg-zinc-100 dark:bg-zinc-900 p-2.5 text-xs font-mono text-zinc-700 dark:text-zinc-300 whitespace-pre">
              {c.message}
            </pre>
          )}
        </div>
      ))}

      {others.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {others.map((c, i) => (
            <li key={`${c.classname}-${c.name}-${i}`} className="text-sm font-mono text-zinc-600 dark:text-zinc-400">
              <span className={OUTCOME_MARK[c.outcome].className}>{OUTCOME_MARK[c.outcome].mark}</span>{' '}
              {caseName(c)}
            </li>
          ))}
        </ul>
      )}

      {(report.status === 'error' || report.status === 'timeout' || report.cases.length === 0) &&
      report.output ? (
        <pre className="overflow-x-auto rounded-md bg-zinc-100 dark:bg-zinc-900 p-2.5 text-xs font-mono text-zinc-700 dark:text-zinc-300 whitespace-pre">
          {report.output}
        </pre>
      ) : (
        report.output && (
          <details>
            <summary className="cursor-pointer text-xs font-mono text-zinc-500 select-none">Full output</summary>
            <pre className="mt-2 overflow-x-auto rounded-md bg-zinc-100 dark:bg-zinc-900 p-2.5 text-xs font-mono text-zinc-700 dark:text-zinc-300 whitespace-pre">
              {report.output}
            </pre>
          </details>
        )
      )}
    </div>
  );
}
