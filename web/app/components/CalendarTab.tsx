export function CalendarTab() {
  return (
    <div className="max-w-2xl">
      <p className="text-4xl mb-4">🔑</p>
      <h2 className="text-lg font-semibold mb-2 text-zinc-900 dark:text-zinc-100">
        Google Calendar &mdash; Setup Required
      </h2>
      <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-6">
        Dayline&apos;s calendar sync runs as a one-time server-side OAuth flow (not a
        browser sign-in), so it&apos;s set up from the backend, not from this page.
      </p>
      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-5">
        <ol className="list-decimal list-inside flex flex-col gap-2 text-sm text-zinc-700 dark:text-zinc-300">
          <li>
            Go to{' '}
            <span className="font-mono text-indigo-600 dark:text-indigo-300">console.cloud.google.com</span> and
            create (or pick) a project.
          </li>
          <li>Enable the Google Calendar API for that project.</li>
          <li>
            Configure the OAuth consent screen, then create an OAuth client ID
            (application type: Desktop app).
          </li>
          <li>
            Download the JSON and save it as{' '}
            <span className="font-mono text-indigo-600 dark:text-indigo-300">credentials.json</span> in the
            repo root.
          </li>
          <li>
            Run the backend once with{' '}
            <span className="font-mono text-indigo-600 dark:text-indigo-300">GoogleCalendarClient()</span>{' '}
            constructed &mdash; it opens a one-time browser consent flow and writes{' '}
            <span className="font-mono text-indigo-600 dark:text-indigo-300">token.json</span>.
          </li>
        </ol>
        <p className="text-xs text-zinc-500 mt-4">Full steps: see GOOGLE_SETUP.md in the repo.</p>
      </div>
    </div>
  );
}
