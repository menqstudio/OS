// jest-dom matchers (toBeInTheDocument, etc.) for all tests.
import '@testing-library/jest-dom';

import { beforeEach } from 'vitest';
import { configure } from '@testing-library/react';

// `T-040`. The suite raised the timeout it knew about and left the one that actually fires.
//
// `vitest.config.ts` sets `testTimeout: 30_000` with the right reasoning -- *"vitest's 5s default is
// not enough for the render suites on a loaded machine, and the failures it produced were
// indistinguishable from real ones."* Testing Library has a SECOND timeout, `asyncUtilTimeout`, which
// every `findBy*` and `waitFor` uses, and it defaults to **1000 ms**. So a test was given thirty
// seconds to run while each wait inside it gave up after one.
//
// MEASURED, because `T-040` asked for the number before the choice. `GroupChat.readout`'s
// PARTICIPANT value arrives **200 ms** after mount in isolation -- five times inside the default. A
// full run is 80 files sharing one machine and reports ~1450 s of environment time; a 5x margin does
// not survive that, and it did not: `GroupChat.readout` failed three times in five full runs, and the
// run that measured this one failed `Approvals.test.tsx` instead, at 1203 ms, with
// `findByRole('dialog')` timing out. Different tests, one cause.
//
// This is NOT either remedy `T-038` warned about. `--retry` hides a real intermittent failure exactly
// once; `singleFork` roughly doubles wall-clock. Waiting longer for something that DOES arrive hides
// nothing -- a genuinely broken test still fails, it just fails later.
//
// The risk it does carry is a real slowdown going unnoticed behind a generous ceiling, so the
// isolated latency is pinned separately: `GroupChat.readout.test.tsx`'s
// `the readout arrives well inside the isolated budget` fails if it stops being fast when nothing
// else is running, which is where "fast" is measurable at all.
configure({ asyncUtilTimeout: 5_000 });

// `T-038`. The suite was load-flaky: one failure in a combined unit+browser+tools run, 732/732 in
// isolation, and nothing recorded WHICH test. It is `Approvals.test.tsx`'s `g`-key case, and the
// cause is not slowness -- it is shared browser state.
//
// `app/store.test.tsx` calls `setLang('hy')`, which writes `localStorage['brops.lang']`. Nothing
// clears it, and vitest reuses a worker across files, so whether `Approvals` inherits Armenian is a
// scheduling detail. When it does, `ConfirmDialog` renders Armenian copy, `findByRole('dialog')`
// still succeeds -- the dialog IS there -- and the synchronous `getByText(/native confirmation…/i)`
// on the next line does not. That is exactly the observed signature: line 100 passed, line 101
// failed.
//
// Reproduced deterministically by seeding `brops.lang` before that test: same error, same line,
// plus a second case the one observed occurrence never showed.
//
// This is NOT one of the two remedies `T-038` warned about. `--poolOptions.forks.singleFork` and a
// job-level `--retry=1` both make a genuine race harder to see; clearing state that was never meant
// to be shared makes the suite MORE deterministic, and it removes the cause rather than the symptom.
beforeEach(() => {
  try {
    localStorage.clear();
    sessionStorage.clear();
  } catch {
    /* a test may run without a DOM; nothing to clear there */
  }
});


// jsdom does not implement matchMedia; several views read it at mount for
// reduced-motion / responsive breakpoints. Provide an inert, non-matching stub so
// component tests can render those views. Tests that need a specific match can
// override window.matchMedia locally.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

// jsdom does not implement scrollIntoView; keyboard-navigable lists (Files, etc.)
// call it to keep the cursor row visible. Stub it as a no-op so those effects don't
// throw during render.
if (typeof Element !== 'undefined' && typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom does not implement ResizeObserver; several views observe a stage element to
// react to size. Provide an inert stub so those mount effects don't throw.
if (typeof globalThis !== 'undefined' && typeof (globalThis as { ResizeObserver?: unknown }).ResizeObserver !== 'function') {
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
