export function StarButton({ starred, onToggle }: { starred: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={starred ? 'Unstar' : 'Star'}
      aria-pressed={starred}
      className={`text-base leading-none ${
        starred
          ? 'text-amber-500 dark:text-amber-400'
          : 'text-zinc-300 dark:text-zinc-600 hover:text-amber-500 dark:hover:text-amber-400'
      }`}
    >
      {starred ? '★' : '☆'}
    </button>
  );
}
