'use client';

import { FileNode } from '../../lib/mock';

// A workspace's files as a folder tree; the open file is highlighted.
export function FileTree({
  nodes,
  depth = 0,
  openPath,
  onOpen,
}: {
  nodes: FileNode[];
  depth?: number;
  openPath: string | null;
  onOpen: (path: string) => void;
}) {
  return (
    <ul>
      {nodes.map((node) => (
        <li key={node.path}>
          {node.children ? (
            <>
              <p
                className="py-1 pr-3 font-mono text-xs text-zinc-500 truncate"
                style={{ paddingLeft: `${1 + depth * 0.75}rem` }}
              >
                {node.name}/
              </p>
              <FileTree nodes={node.children} depth={depth + 1} openPath={openPath} onOpen={onOpen} />
            </>
          ) : (
            <button
              onClick={() => onOpen(node.path)}
              className={`block w-full text-left py-1 pr-3 font-mono text-xs truncate ${
                node.path === openPath
                  ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-900'
              }`}
              style={{ paddingLeft: `${1 + depth * 0.75}rem` }}
              title={node.path}
            >
              {node.name}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
