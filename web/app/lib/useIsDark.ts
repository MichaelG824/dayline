'use client';

import { useEffect, useState } from 'react';

// Tracks the `.dark` class ThemeToggle sets on <html>, for components that
// need the theme in JS (CodeMirror takes it as a prop, not via CSS).
export function useIsDark(): boolean {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains('dark'));
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  return isDark;
}
