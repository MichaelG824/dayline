'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { ThemeToggle } from '../components/ThemeToggle';

function LoginBody() {
  const params = useSearchParams();
  const error = params.get('error');
  const message =
    error === 'state'
      ? 'Sign-in expired. Try Google again.'
      : error
        ? 'Google sign-in failed. Try again.'
        : null;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-8 shadow-sm">
        <div className="flex items-start justify-between mb-6">
          <div>
            <p className="font-mono text-xs tracking-widest text-zinc-500">DAYLINE</p>
            <h1 className="text-2xl font-bold mt-1">Sign in</h1>
          </div>
          <ThemeToggle />
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-6">
          This planner is locked to one Google account. Sign in to prove you own it.
        </p>
        {message && (
          <p className="text-sm text-rose-600 dark:text-rose-400 mb-4">{message}</p>
        )}
        <a
          href="/api/auth/google"
          className="flex items-center justify-center w-full rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 py-2.5 text-sm font-medium hover:border-zinc-400 dark:hover:border-zinc-500"
        >
          Sign in with Google
        </a>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950" />
      }
    >
      <LoginBody />
    </Suspense>
  );
}
