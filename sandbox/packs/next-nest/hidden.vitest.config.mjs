// Runs a staged round's hidden tests (the runner copies them into
// .dayline/hidden for one run) with the pack's settings rather than the
// candidate's config. swc keeps the decorator metadata Nest's dependency
// injection reads, and compiles TSX for React component tests.
import swc from 'unplugin-swc';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  root: '/workspace',
  plugins: [
    swc.vite({
      jsc: {
        parser: { syntax: 'typescript', tsx: true, decorators: true },
        transform: { legacyDecorator: true, decoratorMetadata: true, react: { runtime: 'automatic' } },
      },
    }),
  ],
  test: {
    include: ['.dayline/hidden/**/*.test.{ts,tsx}'],
    environment: 'node',
    setupFiles: ['/opt/pack/hidden.vitest.setup.mjs'],
  },
});
