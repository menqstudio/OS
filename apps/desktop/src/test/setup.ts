// jest-dom matchers (toBeInTheDocument, etc.) for all tests.
import '@testing-library/jest-dom';

import { beforeEach } from 'vitest';

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
