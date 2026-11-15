import 'reflect-metadata';
import { type INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../src/app.module.js';

describe('notes API', () => {
  let app: INestApplication;

  beforeEach(async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleRef.createNestApplication();
    app.useGlobalPipes(new ValidationPipe({ whitelist: true }));
    await app.init();
  });

  afterEach(() => app.close());

  it('creates a note and lists it first', async () => {
    await request(app.getHttpServer()).post('/notes').send({ text: 'Ship it' }).expect(201);
    const res = await request(app.getHttpServer()).get('/notes').expect(200);
    expect(res.body[0].text).toBe('Ship it');
  });

  it('rejects an empty note', async () => {
    await request(app.getHttpServer()).post('/notes').send({ text: '' }).expect(400);
  });
});
