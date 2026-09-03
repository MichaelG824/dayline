'use client';

import { useEffect, useState } from 'react';

const STORAGE_KEY = 'dayline-theme';

export function ThemeToggle() {
  // Starts null (unknown) since the real value lives on <html> and was set
  // by the no-flash script in layout.tsx before React ever ran; syncing in
  // an effect avoids a server/client mismatch on first render.
  const [isDark, setIsDark] = useState<boolean | null>(null);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains('dark'));
  }, []);

  function toggle() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle('dark', next);
    localStorage.setItem(STORAGE_KEY, next ? 'dark' : 'light');
  }

  if (isDark === null) return <div className="w-8 h-8" />;

  return (
    <button
      onClick={toggle}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="w-8 h-8 flex items-center justify-center rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:border-zinc-300 dark:hover:border-zinc-700"
    >
      {isDark ? '☀' : '☽'}
    </button>
  );
}
