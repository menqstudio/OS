import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Analytics } from './Analytics';

/**
 * The reduced-motion contract of the animated total — the property no test in this repository covered.
 *
 * Until 2026-09-20 this page defined its own `useCountUp` whose second parameter was `reduced`, while
 * the two other functions of that name took `animate` and meant the reverse. Consolidating them onto
 * the shared hook means the call site now has to invert the flag (`useEasedCountUp(total, !reduced)`),
 * and a dropped `!` would animate for exactly the users who asked for stillness — silently, with every
 * other test still green, because `matchMedia` was mocked nowhere in the suite.
 *
 * The check is made DETERMINISTIC by stubbing `requestAnimationFrame` to never fire. No frame ever
 * runs, so the rendered number is whatever the hook's state initialiser chose:
 *
 *   * reduced motion + correct polarity -> the true total, at once
 *   * reduced motion + a dropped `!`    -> 0, forever
 *
 * That turns a timing question into a value question, which is the only kind a UI test should ask.
 */

const TOTAL = 42;
let matches = false;

function mockMatchMedia(reduce: boolean) {
  matches = reduce;
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('prefers-reduced-motion') ? matches : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

function setup(reduce: boolean) {
  mockMatchMedia(reduce);
  // No frame ever runs, so nothing but the initial state can put a number on the screen.
  vi.stubGlobal('requestAnimationFrame', () => 0);
  vi.stubGlobal('cancelAnimationFrame', () => {});
  invokeMock.mockImplementation((cmd: string) =>
    Promise.resolve(cmd === 'get_analytics'
      ? [{ key: 'zz_total_probe', label: 'Total Runs Logged', value: TOTAL }]
      : null));
  return render(<AppProvider><ToastProvider><Analytics /></ToastProvider></AppProvider>);
}

/** The animated total is the only `.mono` in the section footer. */
function footText(): string {
  return document.querySelector('.an-foot-r .mono')?.textContent ?? '';
}

/**
 * Wait until the data has rendered AND the effects that follow it have run. `useEasedCountUp` moves
 * its number in a `useEffect`, i.e. one render AFTER `total` changes, so reading the footer the moment
 * the label appears races that effect. It did, on `main` @ e181ee8: "expected '0' to be '42'" with
 * the component correct, and green on the same tree one run earlier.
 */
async function settled(): Promise<void> {
  await waitFor(() => expect(screen.getAllByText('Total Runs Logged').length).toBeGreaterThan(0));
  await waitFor(() => expect(document.querySelector('.an-foot-r .mono')).not.toBeNull());
  await new Promise((r) => setTimeout(r, 50));
}

beforeEach(() => invokeMock.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe('Analytics — the animated total obeys prefers-reduced-motion', () => {
  it('shows the TRUE total with no frames at all when the user asked for reduced motion', async () => {
    setup(true);
    // Inside `waitFor`, so the effect that applies the total is not raced. A dropped `!` is still
    // caught: with frames stubbed out an animating count never leaves 0, and this times out.
    await waitFor(() => expect(footText()).toBe(String(TOTAL)));
  });

  it('animates from zero when motion is allowed — so the flag is read, not ignored', async () => {
    setup(false);
    // Frames are stubbed out, so an animating count is pinned at its starting value. If this read
    // `42` the hook would be snapping for everyone and the test above would pass for the wrong reason.
    // NOT a `waitFor`: a transient 0 would satisfy one even if the hook snapped to 42 a moment later.
    // Settle first, then require it to still be 0.
    await settled();
    expect(footText()).toBe('0');
  });
});
