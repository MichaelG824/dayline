import type { ReactNode } from 'react';
import './globals.css';

export const metadata = {
  title: 'Dayline',
  description: 'A personal planning agent that turns tasks into a time-blocked day.',
};

// Runs before hydration so the page never flashes the wrong theme: applies a
// saved preference immediately, or falls back to the OS setting.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var saved = localStorage.getItem('dayline-theme');
    var dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.classList.toggle('dark', dark);
  } catch (e) {}
})();
`;

// Root layout: wraps every page with the shared <html>/<body> shell. The
// full-bleed dashboard layout (sidebar + main) is owned by AppShell; theme
// colors live in globals.css and react to the `.dark` class set here.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
