# Notes board

A small Rails 8 notes app backed by SQLite.
`NotesController` lists and adds notes; `Note` validates them.

The dev server starts with the sandbox (it runs `bin/rails db:prepare` first) and reloads code as you save.
Restart it from the Preview panel after changing config or adding a migration.
Run the tests with `bin/rails test` (or the Run tests button).

## Part 1 - search

Add a search box above the list that filters notes (case-insensitive) with a `q` parameter, and cover it with a test.

## Part 2 - delete

Let a note be deleted from the list, with a confirmation, and a flash message once it is gone.

## Talk through

- How would you paginate a board with a million notes?
- Where would you add authorization if each note had an owner?
