import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Dedicated accessibility test project. Kept separate from vitest.config.ts so the
// a11y gate can be run (and required) on its own in CI, and so the main unit/component
// run stays fast and free of axe. Uses the same jsdom + React-plugin environment as the
// app build; only the setup file and the `include` glob differ.
//
// The `*.a11y.spec.{ts,tsx}` suffix does NOT match the main config's `*.test.{ts,tsx}`
// glob, so these specs run ONLY here — never twice.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/a11y-setup.ts'],
    css: false,
    include: ['src/**/*.a11y.spec.{ts,tsx}'],
  },
});
