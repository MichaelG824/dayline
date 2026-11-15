import { NoteForm } from './NoteForm';

interface Note {
  id: number;
  text: string;
}

export const dynamic = 'force-dynamic';

async function loadNotes(): Promise<Note[]> {
  const res = await fetch(`${process.env.API_URL ?? 'http://127.0.0.1:4000'}/notes`, {
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return res.json();
}

export default async function Home() {
  const notes = await loadNotes();
  return (
    <main>
      <h1>Notes board</h1>
      <NoteForm />
      <ul>
        {notes.map((note) => (
          <li key={note.id}>{note.text}</li>
        ))}
      </ul>
    </main>
  );
}
