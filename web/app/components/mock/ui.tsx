'use client';

// Small shared pieces for the Mock tab, matching the Problems tab's styling.

export const FIELD =
  'bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm w-full';

export const SELECT =
  'bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm';

export const SECTION_TITLE = 'font-mono text-xs tracking-widest text-zinc-500 mb-2';

export const CARD =
  'rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40';

export const PRIMARY_BUTTON =
  'px-4 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white disabled:opacity-40';

export const SECONDARY_BUTTON =
  'px-4 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:border-zinc-300 dark:hover:border-zinc-700 disabled:opacity-40';

export const QUIET_BUTTON =
  'px-3 py-2 text-sm rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white';

export const DANGER_BUTTON =
  'px-3 py-2 text-sm rounded-lg text-zinc-500 hover:text-rose-600 dark:hover:text-rose-400';

export function Label({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-xs font-mono text-zinc-500 mb-1">
      {children}
    </label>
  );
}

export function BackButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-fit text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
    >
      &lsaquo; {children}
    </button>
  );
}

export function Pill({
  children,
  className = '',
  title,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 ${className}`}
    >
      {children}
    </span>
  );
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-rose-600 dark:text-rose-400">{children}</p>;
}
