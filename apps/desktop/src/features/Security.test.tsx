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
