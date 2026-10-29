'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Renders stored markdown (problem notes, solution explanations). Styled
// per-element since the project doesn't use the Tailwind typography plugin.
export function MarkdownView({ children, empty }: { children: string; empty?: string }) {
  if (!children.trim()) {
    return <p className="text-sm text-zinc-500">{empty ?? 'Nothing here yet.'}</p>;
  }
  return (
    <div className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (props) => <h1 className="mt-4 mb-2 text-lg font-semibold" {...props} />,
          h2: (props) => <h2 className="mt-4 mb-2 text-base font-semibold" {...props} />,
          h3: (props) => <h3 className="mt-3 mb-1 text-sm font-semibold" {...props} />,
          p: (props) => <p className="my-2" {...props} />,
          ul: (props) => <ul className="my-2 list-disc pl-6 [&>li]:mt-1" {...props} />,
          ol: (props) => <ol className="my-2 list-decimal pl-6 [&>li]:mt-1" {...props} />,
          a: (props) => (
            <a
              className="text-indigo-600 dark:text-indigo-400 underline underline-offset-2"
              target="_blank"
              rel="noreferrer"
              {...props}
            />
          ),
          blockquote: (props) => (
            <blockquote
              className="my-2 border-l-2 border-zinc-300 dark:border-zinc-700 pl-3 text-zinc-500"
              {...props}
            />
          ),
          pre: (props) => (
            <pre
              className="my-2 overflow-x-auto rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-3 font-mono text-xs"
              {...props}
            />
          ),
          code: ({ className, children, ...props }) =>
            (className ?? '').includes('language-') ? (
              <code className={className} {...props}>
                {children}
              </code>
            ) : (
              <code className="rounded bg-zinc-100 dark:bg-zinc-800 px-1 py-0.5 font-mono text-xs" {...props}>
                {children}
              </code>
            ),
          table: (props) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs" {...props} />
            </div>
          ),
          th: (props) => (
            <th className="border border-zinc-200 dark:border-zinc-700 px-2 py-1 text-left font-medium" {...props} />
          ),
          td: (props) => <td className="border border-zinc-200 dark:border-zinc-700 px-2 py-1" {...props} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

// A markdown textarea with a Write / Preview toggle.
export function MarkdownField({
  value,
  onChange,
  placeholder,
  rows = 8,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  const [preview, setPreview] = useState(false);
  const tab = (active: boolean) =>
    `px-2.5 py-1 text-xs rounded-md ${
      active
        ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100'
        : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
    }`;
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950">
      <div className="flex items-center gap-1 border-b border-zinc-200 dark:border-zinc-800 px-2 py-1.5">
        <button type="button" onClick={() => setPreview(false)} className={tab(!preview)}>
          Write
        </button>
        <button type="button" onClick={() => setPreview(true)} className={tab(preview)}>
          Preview
        </button>
        <span className="ml-auto text-xs text-zinc-400 dark:text-zinc-600">Markdown</span>
      </div>
      {preview ? (
        <div className="px-3 py-2" style={{ minHeight: `${rows * 1.5}rem` }}>
          <MarkdownView empty="Nothing to preview.">{value}</MarkdownView>
        </div>
      ) : (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={rows}
          className="block w-full resize-y bg-transparent px-3 py-2 text-sm font-mono outline-none"
        />
      )}
    </div>
  );
}
