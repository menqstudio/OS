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
    // The timeouts above treat the symptom; this treats the load. vitest's default worker count is
    // the machine's CPU count minus one, and with 80 jsdom suites that oversubscribes the box: on
    // a 12-CPU Windows machine on 2026-09-19 the default spent 451–474 s in `environment` and
    // 123–145 s in `tests` for a 78–81 s wall clock, while `--maxWorkers=4` spent 200 s and 62 s for
    // 92–96 s — half the contention for a sixth more wall time. `--maxWorkers=2` cost 122–165 s.
    // The T-040 class of failure (`findByRole` timing out under load, a different file each run,
    // every one green in isolation) was NOT reproduced in the six measured runs, so this is not
    // claimed to fix it — it removes the oversubscription that made it likely, which is the only
    // remedy T-040 did not rule out. GitHub's ubuntu runners have 4 cores, so CI is unchanged.
    maxWorkers: 4,
  },
});
