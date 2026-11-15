import { Module } from '@nestjs/common';
import { HealthController } from './health.controller.js';
import { NotesController } from './notes/notes.controller.js';
import { NotesService } from './notes/notes.service.js';

@Module({
  controllers: [HealthController, NotesController],
  providers: [NotesService],
})
export class AppModule {}
