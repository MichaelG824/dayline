import swc from 'unplugin-swc';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    projects: [
      {
        // swc keeps the decorator metadata Nest's dependency injection reads.
        plugins: [swc.vite()],
        test: { name: 'api', root: './api', include: ['test/**/*.test.ts'], environment: 'node' },
      },
      {
        test: {
          name: 'web',
          root: './web',
          include: ['**/*.test.tsx'],
          environment: 'jsdom',
          setupFiles: ['./vitest.setup.ts'],
        },
      },
    ],
  },
});
