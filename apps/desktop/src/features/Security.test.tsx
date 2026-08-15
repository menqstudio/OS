import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Security mirrors engine truth: it reads a real
// summary (get_security_summary) and the real evidence chain (read_evidence_chain),
// and — crucially — it has NO chain-read authority of its own, so it must NEVER
// render a fabricated "verified" posture. The evidence-chain read is unreachable in
// the Phase-2 steady state; the honest integrity is "unverified".
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Security } from './Security';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'get_security_summary')
      return Promise.resolve({ pendingApprovals: 2, decidedApprovals: 5, auditEvents: 10, sensitiveEvents: [] });
    if (cmd === 'read_evidence_chain') return Promise.reject(new Error('broker_unavailable'));
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Security />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Security — mirrors engine truth, never fabricates a verified chain', () => {
  it('reads the real summary + evidence chain and shows an honest UNVERIFIED integrity', async () => {
    setup();
    // The desktop has no chain-read authority: steady state is "Integrity unverified",
    // never a fabricated SECURE/verified posture.
    await waitFor(() => expect(screen.getAllByText('Integrity unverified').length).toBeGreaterThan(0));
    expect(called('get_security_summary')).toBe(true);
    expect(called('read_evidence_chain')).toBe(true);
  });
});

// §D: "Motion: integrity pulse (`sigbreathe`)". The pulse is bound to state — it means
// "this surface is reading the chain right now", never "the chain is alive", which the
// desktop cannot establish (RECORDS_ARE_AUTHENTICATED is permanently false). These tests
// pin the binding in all three directions, because the failure that made them necessary
// was a page that argued for stillness in its comments and animated unconditionally in
// its stylesheet.
describe('Security — the integrity pulse is bound to state, not decorative', () => {
  const instrument = () => document.querySelector('.mani.sec-section');

  it('pulses while the chain read is IN FLIGHT — the one state with real liveness', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'get_security_summary')
        return Promise.resolve({ pendingApprovals: 0, decidedApprovals: 0, auditEvents: 0, sensitiveEvents: [] });
      if (cmd === 'read_evidence_chain') return new Promise(() => {});   // never settles
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Security /></ToastProvider></AppProvider>);
    await waitFor(() => expect(instrument()).toBeTruthy());
    expect(instrument()!.className).toContain('sec-int--checking');
    expect(instrument()!.className).toContain('sigbreathe');
  });

  it('is STILL once the read settles blocked — nothing is established, so nothing breathes', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Integrity unverified').length).toBeGreaterThan(0));
    expect(instrument()!.className).toContain('sec-int--blocked');
    expect(instrument()!.className).not.toContain('sigbreathe');
  });

  it('does NOT breathe on a chain-read failure — that is an alert, not liveness', async () => {
    // hasBackend() is what separates `broken` from `blocked`: a rejected read only means
    // the chain is broken when there was a backend to reject it.
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    try {
      setup();
      await waitFor(() => expect(instrument()?.className).toContain('sec-int--broken'));
      expect(instrument()!.className).not.toContain('sigbreathe');
    } finally {
      delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    }
  });
});
