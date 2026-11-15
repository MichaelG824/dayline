'use client';

import type { ReactNode } from 'react';

export type Tab = 'tasks' | 'problems' | 'mock' | 'interviews' | 'chat' | 'pomodoro';

// Outline icons (Heroicons paths), drawn inline so the nav needs no icon package.
export function NavIcon({ d }: { d: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-5 h-5 shrink-0"
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}

export const MENU_ICON = 'M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5';
export const CLOSE_ICON = 'M6 18 18 6M6 6l12 12';

interface NavItem {
  tab: Tab;
  label: string;
  icon: string;
}

const GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'PLAN',
    items: [
      { tab: 'tasks', label: 'Tasks', icon: 'M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z' },
      {
        tab: 'interviews',
        label: 'Interviews',
        icon: 'M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5',
      },
      {
        tab: 'chat',
        label: 'Chat',
        icon: 'M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z',
      },
      { tab: 'pomodoro', label: 'Pomodoro', icon: 'M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z' },
    ],
  },
  {
    label: 'PRACTICE',
    items: [
      {
        tab: 'problems',
        label: 'LeetCode Problems',
        icon: 'M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5',
      },
      {
        tab: 'mock',
        label: 'AI / Practical Programming',
        icon: 'm6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z',
      },
    ],
  },
];

export function tabLabel(tab: Tab): string {
  for (const group of GROUPS) {
    const item = group.items.find((i) => i.tab === tab);
    if (item) return item.label;
  }
  return tab;
}

interface Props {
  tab: Tab;
  onSelect: (tab: Tab) => void;
  /** MM:SS while the Pomodoro timer runs, shown on its nav item. */
  pomodoroClock: string | null;
}

export function SidebarNav({ tab, onSelect, pomodoroClock }: Props) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-4">
      {GROUPS.map((group) => (
        <div key={group.label}>
          <p className="font-mono text-xs tracking-widest text-zinc-500 mb-1.5">{group.label}</p>
          <ul className="flex flex-col gap-0.5">
            {group.items.map((item) => {
              const active = tab === item.tab;
              let badge: ReactNode = null;
              if (item.tab === 'pomodoro' && pomodoroClock) {
                badge = (
                  <span className="ml-auto font-mono text-xs tabular-nums text-emerald-600 dark:text-emerald-400">
                    {pomodoroClock}
                  </span>
                );
              }
              return (
                <li key={item.tab}>
                  <button
                    type="button"
                    onClick={() => onSelect(item.tab)}
                    aria-current={active ? 'page' : undefined}
                    className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg border text-sm font-medium text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 ${
                      active
                        ? 'bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300 border-indigo-300 dark:border-indigo-500/40'
                        : 'border-transparent text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-900 hover:text-zinc-900 dark:hover:text-zinc-100'
                    }`}
                  >
                    <NavIcon d={item.icon} />
                    <span className="min-w-0 truncate">{item.label}</span>
                    {badge}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
