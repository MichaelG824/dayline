'use client';

export function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-zinc-500 font-semibold';
  if (line.startsWith('@@')) return 'text-indigo-600 dark:text-indigo-400';
  if (line.startsWith('+')) return 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-800 dark:text-emerald-300';
  if (line.startsWith('-')) return 'bg-rose-50 dark:bg-rose-500/10 text-rose-800 dark:text-rose-300';
  return 'text-zinc-600 dark:text-zinc-400';
}

// A unified diff, one colored row per line. The caller provides the frame
// (and its horizontal scroll). `fileHeaders={false}` drops the ---/+++ lines
// when the file name is shown elsewhere.
export function DiffView({ diff, fileHeaders = true }: { diff: string; fileHeaders?: boolean }) {
  let lines = diff.replace(/\n$/, '').split('\n');
  if (!fileHeaders) lines = lines.filter((l) => !l.startsWith('--- ') && !l.startsWith('+++ '));
  return (
    <pre className="min-w-fit py-2 text-xs font-mono">
      {lines.map((line, i) => (
        <div key={i} className={`px-4 whitespace-pre ${diffLineClass(line)}`}>
          {line || ' '}
        </div>
      ))}
    </pre>
  );
}
