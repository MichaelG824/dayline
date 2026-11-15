'use client';

import { useRouter } from 'next/navigation';
import { type FormEvent, useState } from 'react';

const base = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

export function NoteForm() {
  const router = useRouter();
  const [text, setText] = useState('');
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    const res = await fetch(`${base}/api/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      setError('Could not save the note.');
      return;
    }
    setText('');
    setError('');
    router.refresh();
  }

  return (
    <form onSubmit={submit}>
      <input
        aria-label="New note"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Write a note"
      />
      <button type="submit" disabled={!text.trim()}>
        Add
      </button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
