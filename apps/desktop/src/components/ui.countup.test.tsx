import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { useCountUp, useEasedCountUp } from './ui';

/**
 * The two count-up curves, and the flag that had opposite meanings under one name.
 *
 * Until 2026-09-20 this hook existed three times. `components/ui.tsx` and `features/Activity.tsx`
 * held BYTE-IDENTICAL copies (md5 770e7fab…, 575 B) because ui.tsx never exported it, and
 * `features/Analytics.tsx` held a third that diverged twice: a 900 ms cubic ease instead of a 600 ms
 * linear ramp, and a second parameter named `reduced` — the REVERSE of the other two's `animate`.
 *
 * That inversion is the reason these tests exist rather than a comment. Consolidating three functions
 * that share a name is the obvious cleanup, and doing it by name would have made Analytics animate
 * exactly for the users who asked for stillness: an accessibility regression that reads as tidying.
 * So the property pinned here is POLARITY — `true` means move, on both — and it is pinned on both
 * hooks, because the trap is that they might drift apart again.
 *
 * No timing is asserted. The animated cases check the FIRST rendered value (deterministic: the state
 * initialiser runs before any frame) and then that the value arrives, via `waitFor`. Asserting a
 * midpoint would be asserting the frame scheduler, which is how a UI test becomes a flake.
 */

function Probe({ hook, target, animate }: {
  hook: (t: number, a: boolean) => number;
  target: number;
  animate: boolean;
}) {
  return <output data-testid="v">{hook(target, animate)}</output>;
}

const CURVES: Array<[string, (t: number, a: boolean) => number]> = [
  ['useCountUp (600 ms linear)', useCountUp],
  ['useEasedCountUp (900 ms cubic)', useEasedCountUp],
];

describe('the count-up curves agree about what their flag means', () => {
  for (const [name, hook] of CURVES) {
    describe(name, () => {
      it('snaps to the target on the FIRST render when animate is false', () => {
        render(<Probe hook={hook} target={1234} animate={false} />);
        expect(screen.getByTestId('v').textContent).toBe('1234');
      });

      it('starts at zero when animate is true, then arrives', async () => {
        render(<Probe hook={hook} target={42} animate />);
        expect(screen.getByTestId('v').textContent).toBe('0');
        await waitFor(() => expect(screen.getByTestId('v').textContent).toBe('42'));
      });

      it('never overshoots the true value', async () => {
        render(<Probe hook={hook} target={7} animate />);
        await waitFor(() => expect(screen.getByTestId('v').textContent).toBe('7'));
        expect(Number(screen.getByTestId('v').textContent)).toBeLessThanOrEqual(7);
      });

      it('reports zero as zero rather than animating toward nothing', () => {
        render(<Probe hook={hook} target={0} animate />);
        expect(screen.getByTestId('v').textContent).toBe('0');
      });

      it('snaps to a NEW target too, not just the first one', () => {
        // The state initialiser alone satisfies the first-render assertion above, so inverting the
        // effect's guard leaves that one green. A target that changes AFTER mount can only be
        // answered by the effect, which is where the snap actually has to live.
        //
        // The assertion is deliberately SYNCHRONOUS. `rerender` flushes effects inside `act`, so a
        // real snap is on screen immediately, while an animating count is still showing the old
        // value because no frame has run yet. A `waitFor` here would accept both: 600 ms of counting
        // finishes inside its window, and the test would pass on the thing it exists to forbid.
        const { rerender } = render(<Probe hook={hook} target={10} animate={false} />);
        expect(screen.getByTestId('v').textContent).toBe('10');
        rerender(<Probe hook={hook} target={880} animate={false} />);
        expect(screen.getByTestId('v').textContent).toBe('880');
      });
    });
  }

  it('the two curves are interchangeable in their CONTRACT, which is what was not true before', () => {
    // The same call, on both hooks, must mean the same thing. This is the assertion a name-based
    // consolidation would have broken: the deleted Analytics copy returned the target immediately
    // for `true` and animated for `false`.
    const { unmount } = render(<Probe hook={useCountUp} target={99} animate={false} />);
    const linear = screen.getByTestId('v').textContent;
    unmount();
    render(<Probe hook={useEasedCountUp} target={99} animate={false} />);
    expect(screen.getByTestId('v').textContent).toBe(linear);
    expect(linear).toBe('99');
  });
});
