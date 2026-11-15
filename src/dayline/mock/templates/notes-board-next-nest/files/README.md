# Notes board

A small full-stack notes app:

- `web/` - Next.js (App Router). `app/page.tsx` lists notes; `app/NoteForm.tsx` adds one.
- `api/` - NestJS. `src/notes/` holds the notes controller and an in-memory service.

Next forwards the browser's `/api/*` calls to the Nest API, so the preview only needs the web server.
Both dev servers start with the sandbox and reload as you save; restart them from the Preview panel.
Run the tests with `vitest run` (or the Run tests button).

## Part 1 - search

Add a search box above the list that filters notes as you type (case-insensitive).
Do the filtering in the API (`GET /notes?q=...`), and cover it with a test.

## Part 2 - delete

Let a note be deleted from the list: a `DELETE /notes/:id` endpoint that answers 404 for an unknown id, and a button per note.

## Talk through

- The notes live in memory. What changes when they move to a database?
- How would you keep two open tabs in sync?
