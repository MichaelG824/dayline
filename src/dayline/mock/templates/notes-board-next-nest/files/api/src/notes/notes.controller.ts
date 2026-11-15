import { Body, Controller, Get, Post } from '@nestjs/common';
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
    return this.notes.create(body.text);
  }
}
