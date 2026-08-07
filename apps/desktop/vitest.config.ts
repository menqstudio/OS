import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Unit/component tests run in jsdom with the same React plugin as the app build.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
    // vitest's 5s default is not enough for the render suites on a loaded machine, and the failures
    // it produced were indistinguishable from real ones: a different set of pre-existing files went
    // red on every run, all of them passing in isolation. A flaky suite is worse than a slow one —
    // it teaches everyone to re-run instead of read. Raised here rather than per-file so no suite
    // has to opt in, and so nobody has to know which ones are slow.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
