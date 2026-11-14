'use client';

import CodeMirror from '@uiw/react-codemirror';
import type { Extension } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { java } from '@codemirror/lang-java';
import { cpp } from '@codemirror/lang-cpp';
import { go } from '@codemirror/lang-go';
import { rust } from '@codemirror/lang-rust';
import { sql } from '@codemirror/lang-sql';
import { useIsDark } from '../../lib/useIsDark';

// Map a language id (see LANGUAGES in lib/problems.ts) to its grammar.
export function languageExtensions(language: string): Extension[] {
  switch (language) {
    case 'python':
      return [python()];
    case 'javascript':
      return [javascript({ jsx: true })];
    case 'typescript':
      return [javascript({ jsx: true, typescript: true })];
    case 'java':
      return [java()];
    case 'cpp':
      return [cpp()];
    case 'go':
      return [go()];
    case 'rust':
      return [rust()];
    case 'sql':
      return [sql()];
    default:
      return [];
  }
}

// Match the surrounding card instead of CodeMirror's own theme background.
const transparentBackground = EditorView.theme({
  '&': { backgroundColor: 'transparent', fontSize: '0.8rem' },
  '.cm-gutters': { backgroundColor: 'transparent', border: 'none' },
});

// One component for both the solution editor and the read-only code view, so
// edit and display highlight identically.
export function CodeEditor({
  value,
  language,
  onChange,
  readOnly = false,
  minHeight = '220px',
}: {
  value: string;
  language: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  minHeight?: string;
}) {
  const isDark = useIsDark();
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950">
      <CodeMirror
        value={value}
        onChange={onChange}
        theme={isDark ? 'dark' : 'light'}
        editable={!readOnly}
        readOnly={readOnly}
        minHeight={readOnly ? undefined : minHeight}
        extensions={[...languageExtensions(language), transparentBackground, EditorView.lineWrapping]}
        basicSetup={{
          lineNumbers: true,
          foldGutter: false,
          highlightActiveLine: !readOnly,
          highlightActiveLineGutter: !readOnly,
        }}
      />
    </div>
  );
}
