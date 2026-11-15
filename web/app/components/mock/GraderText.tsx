'use client';

// The grader and the interviewer write plain text but mark code with `backticks`.
export function GraderText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`\n]+`)/).map((part, i) =>
        part.length > 2 && part.startsWith('`') && part.endsWith('`') ? (
          <code key={i} className="box-decoration-clone rounded bg-zinc-100 dark:bg-zinc-800/80 px-1 py-px font-mono text-[0.85em]">
            {part.slice(1, -1)}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}
