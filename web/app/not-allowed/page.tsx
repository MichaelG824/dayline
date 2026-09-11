'use client';

import { useEffect, useState } from 'react';
import { getMe, signOut } from '../lib/api';
import { ThemeToggle } from '../components/ThemeToggle';

export default function NotAllowedPage() {
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    void getMe()
      .then((me) => setEmail(me.email))
      .catch(() => setEmail(null));
  }, []);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-8 shadow-sm">
        <div className="flex items-start justify-between mb-6">
          <div>
            <p className="font-mono text-xs tracking-widest text-zinc-500">DAYLINE</p>
            <h1 className="text-2xl font-bold mt-1">Not allowed</h1>
          </div>
          <ThemeToggle />
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-2">
          This Google account cannot use Dayline.
        </p>
        {email && (
          <p className="font-mono text-xs text-zinc-500 mb-6 break-all">{email}</p>
        )}
        {!email && <div className="mb-6" />}
        <button
          type="button"
          onClick={() => void signOut()}
          className="w-full rounded-lg border border-zinc-300 dark:border-zinc-700 py-2.5 text-sm font-medium hover:border-zinc-400 dark:hover:border-zinc-500"
        >
          Sign in with a different account
        </button>
      </div>
    </div>
  );
}
