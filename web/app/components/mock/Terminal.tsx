'use client';

import '@xterm/xterm/css/xterm.css';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal as XTerm } from '@xterm/xterm';
import { useEffect, useRef, useState } from 'react';
import { terminalUrl } from '../../lib/api';
import { useIsDark } from '../../lib/useIsDark';

// xterm colours for each theme, matched to the zinc palette around it.
const THEMES = {
  dark: { background: '#09090b', foreground: '#e4e4e7', cursor: '#a5b4fc', selectionBackground: '#3f3f46' },
  light: { background: '#fafafa', foreground: '#27272a', cursor: '#4f46e5', selectionBackground: '#d4d4d8' },
};

type Status = { kind: 'connecting' } | { kind: 'open' } | { kind: 'closed'; reason: string };

// The sandbox shell. Binary frames carry terminal bytes both ways; resizes go
// up as JSON text frames. A dropped connection shows why and offers a
// reconnect (a fresh shell; files are untouched).
export function Terminal({
  sessionId,
  active,
  focusKey,
}: {
  sessionId: string;
  active: boolean;
  // Changes when the user asks for the terminal; it then takes focus.
  focusKey: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const term = useRef<XTerm | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const [status, setStatus] = useState<Status>({ kind: 'connecting' });
  const [attempt, setAttempt] = useState(0);
  const isDark = useIsDark();

  useEffect(() => {
    if (!host.current) return;
    const xterm = new XTerm({
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 12.5,
      cursorBlink: true,
      scrollback: 5000,
      theme: THEMES.light,
    });
    const fitAddon = new FitAddon();
    xterm.loadAddon(fitAddon);
    xterm.open(host.current);
    term.current = xterm;
    fit.current = fitAddon;
    return () => {
      xterm.dispose();
      term.current = null;
    };
  }, []);

  useEffect(() => {
    if (term.current) term.current.options.theme = isDark ? THEMES.dark : THEMES.light;
  }, [isDark]);

  useEffect(() => {
    const xterm = term.current;
    const fitAddon = fit.current;
    if (!xterm || !fitAddon || !host.current) return;
    fitAddon.fit();
    // A reconnect is a fresh shell; don't leave the old one's screen behind.
    if (attempt > 0) xterm.reset();
    setStatus({ kind: 'connecting' });
    const ws = new WebSocket(terminalUrl(sessionId, xterm.cols, xterm.rows));
    ws.binaryType = 'arraybuffer';
    const encoder = new TextEncoder();

    ws.onopen = () => {
      setStatus({ kind: 'open' });
      xterm.focus();
    };
    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) xterm.write(new Uint8Array(event.data));
      else xterm.write(String(event.data));
    };
    ws.onclose = (event) => {
      const reason =
        event.reason || (event.code === 1006 ? 'Lost connection to the sandbox' : 'Disconnected');
      setStatus({ kind: 'closed', reason });
    };
    const send = (data: string) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data));
    };
    const onData = xterm.onData(send);
    const onBinary = xterm.onBinary((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(Uint8Array.from(data, (c) => c.charCodeAt(0)));
    });
    const onResize = xterm.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    });
    const observer = new ResizeObserver(() => {
      // Hidden (display: none) panels measure 0; fitting then would shrink the shell.
      if (host.current && host.current.offsetWidth > 0) fitAddon.fit();
    });
    observer.observe(host.current);

    return () => {
      observer.disconnect();
      onData.dispose();
      onBinary.dispose();
      onResize.dispose();
      ws.onclose = null;
      ws.close();
    };
  }, [sessionId, attempt]);

  useEffect(() => {
    if (active && term.current) {
      fit.current?.fit();
      term.current.focus();
    }
  }, [active, focusKey]);

  return (
    <div className="relative h-full bg-zinc-50 dark:bg-zinc-950">
      <div ref={host} className="absolute inset-0 pl-3 pt-2" />
      {status.kind !== 'open' && (
        <div className="absolute right-3 top-2 flex items-center gap-3 rounded-md bg-white/90 dark:bg-zinc-900/90 px-3 py-1.5 text-xs shadow-sm ring-1 ring-zinc-200 dark:ring-zinc-800">
          <span className="text-zinc-500">
            {status.kind === 'connecting' ? 'Connecting to the sandbox…' : status.reason}
          </span>
          {status.kind === 'closed' && (
            <button
              onClick={() => setAttempt((n) => n + 1)}
              className="text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Reconnect
            </button>
          )}
        </div>
      )}
    </div>
  );
}
