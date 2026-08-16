import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { playwright } from '@vitest/browser-playwright';

// The THIRD test project, and the only one that measures rather than reads.
//
// `vitest.config.ts` and `vitest.a11y.config.ts` both set `css: false`. That is not a detail:
// it means 713 unit tests and 59 axe checks run against a DOM with **no stylesheet attached**,
// so every assertion about appearance in this repository is really an assertion about a
// className string. `A-01` is what that costs — a test asserted the token `sigbreathe` was in a
// class list (it was) while the element it named rendered at `opacity: 0`, invisible, and shipped.
//
// This project exists to close that gap with a MEASUREMENT. Real Chromium, real CSSOM, the app's
// real stylesheet graph, and the component's own `<style>` block — which matters more here than
// it would in most codebases, because 28 of this app's pages carry their CSS in a template
// literal *inside the component*. A harness that loaded `tokens.css + aios.css + ui.css` against
// a hand-written fixture would have missed `A-01` entirely: the broken rule was in `Security.tsx`.
//
// So the components are MOUNTED, not approximated. `css: true` here is the whole point.
//
// The `*.browser.spec.{ts,tsx}` suffix matches neither of the other two globs
// (`*.test.{ts,tsx}`, `*.a11y.spec.{ts,tsx}`), so these run only here — never twice, and never
// in jsdom, where they would be meaningless.
export default defineConfig({
  plugins: [react()],
  test: {
    css: true,
    globals: true,
    setupFiles: ['./src/test/browser-setup.ts'],
    include: ['src/**/*.browser.spec.{ts,tsx}'],
    // A real browser start plus 23 page mounts is slower than jsdom by a wide margin, and a
    // timeout failure here looks exactly like a real one — the lesson already recorded in
    // vitest.config.ts.
    testTimeout: 60_000,
    hookTimeout: 60_000,
    browser: {
      enabled: true,
      provider: playwright(),
      headless: true,
      screenshotFailures: false,
      instances: [{ browser: 'chromium' }],
    },
  },
});
