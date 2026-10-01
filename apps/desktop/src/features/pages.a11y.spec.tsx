import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { axe } from '../test/axe';

// The IPC boundary. Every page here reads real commands and has no fixture layer behind it, so
// the mock decides which STATE each page renders. That is the point: an accessibility pass over
// the happy path only is a pass over the state a user is least often stuck in.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class { onmessage: unknown = null; },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Shell } from '../components/Shell';
import { CommandPalette } from '../components/CommandPalette';
// The page list and the command fixtures are the SHARED ones. This file used to carry its own
// copy of both — a second `PAGES`, a second `OBJECT_SHAPED` — which is the duplication
// `pages.fixtures.tsx` was extracted to end, and its own header names this spec as the place the
// second copy lived.
import { PAGES, arrange } from './pages.fixtures';

/**
 * Accessibility (axe) coverage for the SURFACES, not just the primitives.
 *
 * The fifth independent audit's §E named this gap precisely: the only `*.a11y.spec.tsx` files in
 * this repository covered `ui.tsx` and the shared primitives, so *"the modal this round rebuilt
 * for accessibility is not in the axe pass, and neither is Security, Approvals, or any of the 23
 * pages."* A component library can be perfectly accessible while every page composed from it is
 * not — the violations that matter (a heading level skipped, two elements sharing an id, a live
 * region with no accessible name, a control labelled only by an icon) are properties of the
 * composition, and the composition was untested.
 *
 * WHAT THIS CANNOT DO, said plainly rather than implied. jsdom attaches no stylesheet — this
 * project runs with `css: false`, which is what let A-01 ship — so axe's `color-contrast` rule
 * cannot execute here and does not. Contrast is covered separately and statically by
 * `tools/check_contrast.py` over the committed token pairs. What runs here is the structural
 * half: roles, accessible names, ARIA validity, duplicate ids, landmark and heading structure.
 * That is most of what a page gets wrong, and none of it was being checked.
 */

// The three arrangements come from `pages.fixtures.tsx`:
//
//   * `settled`     — every command answers an EMPTY, shape-correct result (`list_dir` is an
//                     object with an `entries` array; answering it `[]` yields
//                     `Array.prototype.entries`, a function, and the page dies on `.filter`);
//   * `populated`   — typed rows for every list the pages read;
//   * `unreachable` — every command rejects, the state this cockpit is designed around.

function mount(node: React.ReactNode) {
  return render(<AppProvider><ToastProvider>{node}</ToastProvider></AppProvider>);
}

/** Let the page's `useAsync` reads settle before axe looks at the DOM. */
async function settled() {
  await waitFor(() => expect(invokeMock).toHaveBeenCalled());
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => invokeMock.mockReset());
// Unmount FIRST, then reset. A populated page has cleanup effects that call the backend (the open
// thread cancels its reply on unmount); resetting the mock before the unmount hands those effects
// an `invoke` that returns `undefined`, which is a crash in the harness, not in the page.
afterEach(() => { cleanup(); invokeMock.mockReset(); });

// EVERY routed feature page, not a sample — `PAGES` is the list the browser sweeps mount too. The
// first version of this file covered six, which was the six the fifth audit's §E named plus the
// ones nearest them — and a sample is how a page ends up being the one nobody checked. `Chat` and
// `GroupChat` both render `Conversations`, so the shared surface is covered through them.
describe('accessibility (axe) — the pages, in the state a reader actually meets', () => {
  for (const [name, page] of PAGES) {
    it(`${name} has no violations when every read is empty`, async () => {
      // This test was called "with data" and called `empty()`: it mounted the empty state under
      // the populated state's name, and no page was ever checked with a row in it.
      arrange(invokeMock, 'settled');
      const { container } = mount(<main>{page()}</main>);
      await settled();
      expect(await axe(container)).toHaveNoViolations();
    });

    it(`${name} has no violations with data`, async () => {
      // Rows on screen: list items, per-row controls, badges, the selected-item panes. Most of a
      // page's markup only exists in this state.
      arrange(invokeMock, 'populated');
      const { container } = mount(<main>{page()}</main>);
      await settled();
      expect(await axe(container)).toHaveNoViolations();
    });

    it(`${name} has no violations when the engine is unreachable`, async () => {
      // The state this whole cockpit is designed around — a fail-closed engine — and the one an
      // accessibility pass over the happy path would never visit.
      arrange(invokeMock, 'unreachable');
      const { container } = mount(<main>{page()}</main>);
      await settled();
      expect(await axe(container)).toHaveNoViolations();
    });
  }
});

describe('accessibility (axe) — the shell and its modal', () => {
  it('the app frame has no violations', async () => {
    arrange(invokeMock, 'settled');
    const { container } = mount(<Shell><h1>Stage</h1></Shell>);
    await settled();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('the ⌘K command dock has no violations while OPEN', async () => {
    // The surface §D nominates as the keyboard route to all 23 pages, rebuilt for accessibility
    // in this phase and — until now — absent from the axe pass entirely.
    arrange(invokeMock, 'settled');
    const { container } = mount(<><CommandPalette /><main><h1>Stage</h1></main></>);
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    });
    await screen.findByRole('dialog');
    expect(await axe(container)).toHaveNoViolations();
  });
});
