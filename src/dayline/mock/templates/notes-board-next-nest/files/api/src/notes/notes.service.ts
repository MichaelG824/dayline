import { Injectable } from '@nestjs/common';

export interface Note {
  id: number;
  text: string;
  createdAt: string;
}

@Injectable()
export class NotesService {
  private notes: Note[] = [
    { id: 1, text: 'Read the README', createdAt: new Date().toISOString() },
  ];
  private nextId = 2;

  list(): Note[] {
    return [...this.notes].reverse();
  }

  create(text: string): Note {
    const note = { id: this.nextId++, text: text.trim(), createdAt: new Date().toISOString() };
    this.notes.push(note);
    return note;
  }
}
