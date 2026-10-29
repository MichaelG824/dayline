import { DIFFICULTY_BADGE, STATUS_BADGE } from '../../lib/problems';

const PILL = 'inline-flex items-center text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap';

export function DifficultyBadge({ difficulty }: { difficulty: string }) {
  return <span className={`${PILL} ${DIFFICULTY_BADGE[difficulty] ?? ''}`}>{difficulty}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`${PILL} ${STATUS_BADGE[status] ?? ''}`}>{status}</span>;
}

export function TagChip({ name, color }: { name: string; color: string | null }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 whitespace-nowrap"
      style={color ? { borderColor: color } : undefined}
    >
      {color && <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />}
      {name}
    </span>
  );
}
