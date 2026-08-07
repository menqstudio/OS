// The desktop wrappers for the bridge surfaces that were registered in Rust but reachable from no
// renderer code: `read_decision_ledger`, `read_verifier_verdicts`, and the `governed_turn_execute`
// thin proxy behind `governedTurnAttempt`.
//
// These specs pin the two things a wrapper can get wrong here: calling the wrong command (a governance
// surface silently reading someone else's data) and softening a failure into something hopeful.

import { describe, it, expect, vi, beforeEach } from 'vitest';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { desktop, governedTurnAttempt } from './desktop';
import { RESULT_PROTOCOL, TRUSTED_VERIFIED } from './governedTurn';

beforeEach(() => {
  invokeMock.mockReset();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

/** Pretend we are inside the Tauri runtime, so `governedTurnAttempt` reaches the proxy. */
function withBackend() {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
}

describe('governance mirrors that had no renderer wrapper', () => {
  it('readDecisionLedger reads the ENGINE ledger command, not the local decisions table', async () => {
    invokeMock.mockResolvedValue({ state: 'ok', surface: 'decisionLedger', records: [{ id: 'x' }], authenticated: false });
    const r = await desktop.readDecisionLedger();
    expect(invokeMock).toHaveBeenCalledWith('read_decision_ledger', undefined);
    // `list_decisions` is a different, local surface — reading one must never be reading the other.
    expect(invokeMock).not.toHaveBeenCalledWith('list_decisions', expect.anything());
    expect(r.state).toBe('ok');
    // The backend does not claim authentication, so neither does the wrapper.
    expect(r.authenticated).toBe(false);
  });

  it('readVerifierVerdicts passes the task filter, and null when unfiltered', async () => {
    invokeMock.mockResolvedValue({ state: 'ok', surface: 'verdicts', records: [], authenticated: false });
    await desktop.readVerifierVerdicts('d-1');
    expect(invokeMock).toHaveBeenCalledWith('read_verifier_verdicts', { taskId: 'd-1' });
    await desktop.readVerifierVerdicts();
    expect(invokeMock).toHaveBeenLastCalledWith('read_verifier_verdicts', { taskId: null });
  });

  it('both fail closed to `unreachable` when the IPC rejects — never to `ok`', async () => {
    invokeMock.mockRejectedValue(new Error('broker_unavailable: nope'));
    for (const r of [await desktop.readDecisionLedger(), await desktop.readVerifierVerdicts('d-1')]) {
      expect(r.state).toBe('unreachable');
      expect(r.authenticated).toBe(false);
      expect(r.reason).toContain('broker_unavailable');
    }
  });

  it('an `ok` reply the desktop cannot authenticate is never reported as authenticated', async () => {
    // Fail-closed: only a literal `true` from the backend counts, and the backend does not send it.
    invokeMock.mockResolvedValue({ state: 'ok', surface: 'verdicts', records: [{ verdict: 'GREEN' }], authenticated: 'yes' });
    const r = await desktop.readVerifierVerdicts();
    expect(r.authenticated).toBe(false);
  });
});

describe('governedTurnAttempt — the UI-facing governed turn', () => {
  it('short-circuits to `no_desktop_backend` outside a Tauri runtime, contacting nothing', async () => {
    const a = await governedTurnAttempt('conv-1');
    expect(a.status).toBe('unavailable');
    if (a.status === 'unavailable') expect(a.kind).toBe('no_desktop_backend');
    // No broker was addressable, so no invoke may have been attempted.
    expect(invokeMock).not.toHaveBeenCalled();
  });

  it('invokes the thin proxy with the closed frame and nothing else', async () => {
    withBackend();
    invokeMock.mockRejectedValue(new Error('broker_unavailable: no socket'));
    await governedTurnAttempt('conv-1', 'agent-x');
    const [cmd, args] = invokeMock.mock.calls[0] as [string, { request: Record<string, unknown> }];
    expect(cmd).toBe('governed_turn_execute');
    expect(Object.keys(args.request).sort())
      .toEqual(['agent', 'client_request_id', 'conversation_id', 'protocol']);
  });

  it('a proxy rejection resolves as `unavailable`, keeping "unreached" apart from "refused"', async () => {
    withBackend();
    invokeMock.mockRejectedValue(new Error('broker_unsupported_platform: no transport (os=win32)'));
    const a = await governedTurnAttempt('conv-1');
    expect(a.status).toBe('unavailable');
    if (a.status === 'unavailable') expect(a.kind).toBe('broker_unsupported_platform');
  });

  it('a real broker refusal is returned as a `blocked` DECISION, not as unavailable', async () => {
    withBackend();
    invokeMock.mockResolvedValue({
      protocol: RESULT_PROTOCOL, status: 'blocked', client_request_id: 'x',
      broker_turn_id: 'bt-9', conversation_id: 'conv-1', reason: 'upstream_blocked',
    });
    const a = await governedTurnAttempt('conv-1');
    expect(a.status).toBe('blocked');
  });

  it('cannot be talked into `trusted_verified` by a reply that is not a broker committed frame', async () => {
    withBackend();
    // A hostile reply that says all the right words but is not a legal frame.
    invokeMock.mockResolvedValue({
      protocol: 'brops.not-the-result-protocol', status: 'committed', client_request_id: 'x',
      broker_turn_id: 'bt-9', conversation_id: 'conv-1',
      message: { message_id: 'm', role: 'assistant', author: 'a', body: 'b', created_at_ms: 1, trust_state: TRUSTED_VERIFIED },
    });
    const a = await governedTurnAttempt('conv-1');
    expect(a.status).toBe('unavailable');
    if (a.status === 'unavailable') expect(a.kind).toBe('malformed_broker_reply');
  });
});
