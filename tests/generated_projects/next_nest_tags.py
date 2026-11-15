"""A generated project for the next-nest stack, as the model would submit it
(the ``submit_project`` tool input): the scaffold's notes board, a task to
add tags, and a change request to filter by tag.

It is a real, working project: the opt-in Docker test validates it end to
end, and the unit tests use it as the fake model's reply.
"""

from __future__ import annotations

from typing import Any

README = """# Notes board

A small full-stack notes app:

- `web/` - Next.js (App Router). `app/page.tsx` lists notes; `app/NoteForm.tsx` adds one.
- `api/` - NestJS. `src/notes/` holds the notes controller, its DTO and an in-memory service.

Next forwards the browser's `/api/*` calls to the Nest API, so the preview only needs the web server.
Run the tests with `vitest run` (or the Run tests button).
"""

DTO_TAGS = """import {
  ArrayMaxSize,
  IsArray,
  IsNotEmpty,
  IsOptional,
  IsString,
  MaxLength,
} from 'class-validator';

export class CreateNoteDto {
  @IsString()
  @IsNotEmpty()
  @MaxLength(200)
  text: string;

  @IsOptional()
  @IsArray()
  @ArrayMaxSize(5)
  @IsString({ each: true })
  tags?: string[];
}
"""

SERVICE_TAGS = """import { Injectable } from '@nestjs/common';

export interface Note {
  id: number;
  text: string;
  tags: string[];
  createdAt: string;
}

function normalise(tags: string[]): string[] {
  return [...new Set(tags.map((tag) => tag.trim().toLowerCase()).filter(Boolean))];
}

@Injectable()
export class NotesService {
  private notes: Note[] = [
    { id: 1, text: 'Read the README', tags: ['welcome'], createdAt: new Date().toISOString() },
  ];
  private nextId = 2;

  list(): Note[] {
    return [...this.notes].reverse();
  }

  create(text: string, tags: string[] = []): Note {
    const note = {
      id: this.nextId++,
      text: text.trim(),
      tags: normalise(tags),
      createdAt: new Date().toISOString(),
    };
    this.notes.push(note);
    return note;
  }
}
"""

CONTROLLER_TAGS = """import { Body, Controller, Get, Post } from '@nestjs/common';
import { CreateNoteDto } from './create-note.dto.js';
import { NotesService } from './notes.service.js';

@Controller('notes')
export class NotesController {
  constructor(private readonly notes: NotesService) {}

  @Get()
  list() {
    return this.notes.list();
  }

  @Post()
  create(@Body() body: CreateNoteDto) {
    return this.notes.create(body.text, body.tags);
  }
}
"""

SERVICE_FILTER = SERVICE_TAGS.replace(
    """  list(): Note[] {
    return [...this.notes].reverse();
  }""",
    """  list(tag?: string): Note[] {
    const wanted = tag?.trim().toLowerCase();
    const notes = wanted ? this.notes.filter((note) => note.tags.includes(wanted)) : this.notes;
    return [...notes].reverse();
  }""",
)

CONTROLLER_FILTER = CONTROLLER_TAGS.replace(
    "Body, Controller, Get, Post", "Body, Controller, Get, Post, Query"
).replace(
    """  list() {
    return this.notes.list();""",
    """  list(@Query('tag') tag?: string) {
    return this.notes.list(tag);""",
)

_APP = """import 'reflect-metadata';
import { type INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../../api/src/app.module.js';

async function boot(): Promise<INestApplication> {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  const app = moduleRef.createNestApplication();
  app.useGlobalPipes(new ValidationPipe({ whitelist: true }));
  await app.init();
  return app;
}
"""

TAGS_TEST = (
    _APP
    + """
describe('task: tags', () => {
  let app: INestApplication;
  beforeEach(async () => {
    app = await boot();
  });
  afterEach(() => app.close());

  it('saves normalised tags', async () => {
    const res = await request(app.getHttpServer())
      .post('/notes')
      .send({ text: 'Plan the week', tags: [' Work ', 'work', 'Ideas'] })
      .expect(201);
    expect(res.body.tags).toEqual(['work', 'ideas']);
  });

  it('lists notes with their tags', async () => {
    await request(app.getHttpServer()).post('/notes').send({ text: 'Gym', tags: ['health'] });
    const res = await request(app.getHttpServer()).get('/notes').expect(200);
    expect(res.body[0].tags).toEqual(['health']);
  });

  it('rejects more than five tags', async () => {
    await request(app.getHttpServer())
      .post('/notes')
      .send({ text: 'Too many', tags: ['a', 'b', 'c', 'd', 'e', 'f'] })
      .expect(400);
  });
});
"""
)

FILTER_TEST = (
    _APP
    + """
describe('change request: filter by tag', () => {
  let app: INestApplication;
  beforeEach(async () => {
    app = await boot();
  });
  afterEach(() => app.close());

  it('only lists notes with the tag', async () => {
    await request(app.getHttpServer()).post('/notes').send({ text: 'Report', tags: ['work'] });
    await request(app.getHttpServer()).post('/notes').send({ text: 'Gym', tags: ['health'] });
    const res = await request(app.getHttpServer()).get('/notes?tag=Work').expect(200);
    expect(res.body.map((n: { text: string }) => n.text)).toEqual(['Report']);
  });

  it('lists nothing for an unknown tag', async () => {
    const res = await request(app.getHttpServer()).get('/notes?tag=nope').expect(200);
    expect(res.body).toEqual([]);
  });
});
"""
)


def submit_input() -> dict[str, Any]:
    return {
        "title": "Tagged notes board",
        "summary": "A Next.js + NestJS notes board: add tags, then filter by them.",
        "open_path": "README.md",
        "files": [{"path": "README.md", "content": README}],
        "delete": [],
        "task": {
            "title": "Tag notes",
            "prompt_md": (
                "Let a note carry up to five tags. `POST /notes` accepts an optional `tags` "
                "array; tags are trimmed, lower-cased and de-duplicated, and every note in "
                "`GET /notes` includes its `tags`. More than five tags is a 400."
            ),
            "notes_md": "Probe validation: where does normalising belong, DTO or service?",
            "target_min": 25,
            "tests": [{"name": "tags.test.ts", "content": TAGS_TEST}],
            "reference": [
                {"path": "api/src/notes/create-note.dto.ts", "content": DTO_TAGS},
                {"path": "api/src/notes/notes.service.ts", "content": SERVICE_TAGS},
                {"path": "api/src/notes/notes.controller.ts", "content": CONTROLLER_TAGS},
            ],
            "edge_cases": [
                {"id": "normalise", "title": "Normalises tags", "tests": ["saves normalised tags"]},
                {
                    "id": "limit",
                    "title": "Caps tags at five",
                    "tests": ["rejects more than five tags", "a test that does not exist"],
                },
            ],
        },
        "change_request": {
            "title": "Filter by tag",
            "prompt_md": "Product wants `GET /notes?tag=work` to list only notes with that tag.",
            "notes_md": "Watch whether they match tags case-insensitively.",
            "target_min": 20,
            "tests": [{"name": "filter.test.ts", "content": FILTER_TEST}],
            "reference": [
                {"path": "api/src/notes/notes.service.ts", "content": SERVICE_FILTER},
                {"path": "api/src/notes/notes.controller.ts", "content": CONTROLLER_FILTER},
            ],
            "edge_cases": [
                {
                    "id": "unknown",
                    "title": "Unknown tag",
                    "tests": ["lists nothing for an unknown tag"],
                }
            ],
        },
        "analysis_hints": [
            "Did they read the DTO and ValidationPipe setup before adding a field?",
            "Did they normalise tags in one place?",
        ],
    }
