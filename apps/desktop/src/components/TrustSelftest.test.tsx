import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import type { TrustSelftest } from '../services/desktop';
import { TrustSelftestPanel } from './TrustSelftest';

// The panel had three outcomes on screen — unavailable, passed, threw — and a fourth it rendered
// as NOTHING: the chain ran on this platform and did not verify. That is the one result an owner
// most needs to read, and an empty region under a button reads as "nothing happened" or, worse,
// as a pass that has not painted yet.

function result(over: Partial<TrustSelftest>): TrustSelftest {
  return {
    available: true,
    trust_state: 'trusted_verified',
    // What the in-process kit really returns on a good run: custody is the demonstration anchor,
    // so this is ALWAYS false. A fixture with `true` here tests a result that does not exist.
    production_verified: false,
    demonstration_custody: true,
    answer_source: 'builtin_placeholder_no_model_configured',
    answer_is_from_a_model: false,
    bound: true,
    chain_bound: true,
    detail: 'trusted_verified(demonstration_custody key=k-1 epoch=1 root=demo)',
    answer: 'demonstration reply',
    custody_note: 'demonstration custody',
    platform_note: '',
    ...over,
  };
}

async function run(r: TrustSelftest) {
  invokeMock.mockImplementation((cmd: string) =>
    cmd === 'governed_trust_selftest' ? Promise.resolve(r) : Promise.reject(new Error(`unmocked: ${cmd}`)),
  );
  render(
    <AppProvider>
      <TrustSelftestPanel />
    </AppProvider>,
  );
  const panel = screen.getByRole('region');
  fireEvent.click(within(panel).getByRole('button'));
  await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('governed_trust_selftest'));
  return panel;
}

describe('TrustSelftestPanel — a chain that ran and did not verify is said, not left blank', () => {
  beforeEach(() => {
    invokeMock.mockReset();
  });

  it('a good run — bound, chain bound, demonstration custody — paints PASSED and names the custody', async () => {
    // This is the shape `governed_trust_selftest` returns when everything works, and for as long
    // as the panel gated on `production_verified` it rendered NOTHING for it.
    const panel = await run(result({}));
    await waitFor(() => expect(within(panel).getByText('SELF-TEST PASSED')).toBeTruthy());
    expect(within(panel).getByText('DEMONSTRATION CUSTODY')).toBeTruthy();
    expect(within(panel).queryByText('SELF-TEST DID NOT VERIFY')).toBeNull();
  });

  it.each([
    ['the committed row is not what the receipt bound', { bound: false, trust_state: '', detail: 'trusted_verified(demonstration_custody key=k-1 epoch=1 root=demo)' }],
    ['the chain resolved no key under a verified anchor', { chain_bound: false, trust_state: 'trusted_verified', detail: 'no_trusted_manifest(root_unknown)' }],
  ] as const)('%s: the screen says it did not verify, and why', async (_name, over) => {
    const panel = await run(result(over));
    const verdict = await waitFor(() => within(panel).getByText('SELF-TEST DID NOT VERIFY'));
    expect(verdict).toBeTruthy();
    // The kit's own account of what happened is on screen, not a generic sentence.
    expect(within(panel).getByText(over.detail)).toBeTruthy();
    // And nothing on screen reads as a pass: no verdict, and none of the pass chain's steps.
    expect(within(panel).queryByText('SELF-TEST PASSED')).toBeNull();
    expect(within(panel).queryByText('challenge')).toBeNull();
    // `trust_state` is set from `bound` alone, so it can read trusted_verified on a failed run.
    expect(within(panel).queryByText('trusted_verified')).toBeNull();
  });
});
