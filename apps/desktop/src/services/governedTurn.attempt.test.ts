// The renderer's governed-turn NON-DECISION taxonomy.
//
// The point of these specs is one distinction the UI must never lose: a broker that was reached and
// REFUSED is a verdict; a broker that was never reached, or that answered garbage, is the absence of a
// verdict. `runGovernedTurn` collapses the second into a rejected promise, which is exactly how a UI
// ends up rendering "we could not connect" as "you were denied". `attemptGovernedTurn` keeps them apart,
// and nothing it returns can reach a "Verified" affordance except a real broker `committed` frame.

import { describe, it, expect } from 'vitest';
import {
  attemptGovernedTurn, classifyTransportFailure, isBrokerDecision, isVerified,
  NON_DECISIONS, RESULT_PROTOCOL, TRUSTED_VERIFIED,
  type BrokerTransport, type GovernedTurnAttempt,
} from './governedTurn';

const CRID = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';
const genId = () => CRID;

function committedFrame() {
  return {
    protocol: RESULT_PROTOCOL,
    status: 'committed',
    client_request_id: CRID,
    broker_turn_id: 'bt-1',
    conversation_id: 'conv-1',
    message: {
      message_id: 'm-1', role: 'assistant', author: 'Bro', body: 'hello',
      created_at_ms: 1700, trust_state: TRUSTED_VERIFIED,
    },
  };
}
function blockedFrame(reason: string) {
  return {
    protocol: RESULT_PROTOCOL, status: 'blocked', client_request_id: CRID,
    broker_turn_id: 'bt-1', conversation_id: 'conv-1', reason,
  };
}

const rejecting = (message: string): BrokerTransport => () => Promise.reject(new Error(message));
const resolving = (v: unknown): BrokerTransport => () => Promise.resolve(v);

/** Narrow to the unavailable arm so the assertions read the fields directly. */
function unavailable(a: GovernedTurnAttempt) {
  if (a.status !== 'unavailable') throw new Error(`expected unavailable, got ${a.status}`);
  return a;
}

describe('classifyTransportFailure — the proxy prefixes survive into the renderer', () => {
  // The exact reason strings `src-tauri/src/governed_turn.rs` produces, prefix + prose. The Rust side
  // has its own test that these three prefixes stay mutually distinguishable; this is the other half of
  // that contract, on the consuming side.
  it.each([
    ['broker_unsupported_platform: no governed-broker IPC transport is implemented for this host (os=windows, arch=x86_64).', 'broker_unsupported_platform'],
    ['broker_unavailable: a broker IPC transport is implemented for this host but the connection to `/run/brops/broker.sock` could not be established (connect: NotFound).', 'broker_unavailable'],
    ['broker_transport_failed: connected to the broker, but the framed exchange failed (Io).', 'broker_transport_failed'],
    ['malformed_request', 'malformed_request'],
    ['malformed_broker_reply', 'malformed_broker_reply'],
  ])('classifies %s', (message, kind) => {
    const c = classifyTransportFailure(new Error(message));
    expect(c.kind).toBe(kind);
    // The verbatim machine reason is preserved for display and logs.
    expect(c.detail).toBe(message);
  });

  it('never invents a named cause for an unrecognised rejection', () => {
    const c = classifyTransportFailure(new Error('some totally unexpected failure'));
    expect(c.kind).toBe('unclassified_transport_failure');
    expect(c.detail).toBe('some totally unexpected failure');
  });

  it('does not let "not implemented on this platform" masquerade as "could not connect"', () => {
    // The Rust audit finding, asserted from the renderer: these two must not share a classification.
    const unsupported = classifyTransportFailure(new Error('broker_unsupported_platform: ...'));
    const unavailableKind = classifyTransportFailure(new Error('broker_unavailable: ...'));
    expect(unsupported.kind).not.toBe(unavailableKind.kind);
  });

  it('every taxonomy member is distinct', () => {
    expect(new Set(NON_DECISIONS).size).toBe(NON_DECISIONS.length);
  });
});

describe('attemptGovernedTurn — a non-decision is never a verdict', () => {
  it('returns the broker decision when the broker committed', async () => {
    const a = await attemptGovernedTurn('conv-1', undefined, resolving(committedFrame()), genId);
    expect(a.status).toBe('committed');
    expect(isBrokerDecision(a)).toBe(true);
    expect(isVerified(a)).toBe(true);
  });

  it('returns the broker decision when the broker refused — blocked stays blocked', async () => {
    const a = await attemptGovernedTurn('conv-1', undefined, resolving(blockedFrame('upstream_blocked')), genId);
    expect(a.status).toBe('blocked');
    if (a.status === 'blocked') expect(a.reason).toBe('upstream_blocked');
    // A refusal IS a broker decision, and it is not verified.
    expect(isBrokerDecision(a)).toBe(true);
    expect(isVerified(a)).toBe(false);
  });

  it('a transport failure is `unavailable`, NOT `blocked`', async () => {
    const a = await attemptGovernedTurn('conv-1', undefined, rejecting('broker_unavailable: connect failed'), genId);
    const u = unavailable(a);
    expect(u.kind).toBe('broker_unavailable');
    // The whole point: this must not be readable as a refusal.
    expect(isBrokerDecision(a)).toBe(false);
    expect(isVerified(a)).toBe(false);
  });

  it('a platform with no transport is `unavailable`, and says which non-decision it was', async () => {
    const a = await attemptGovernedTurn(
      'conv-1', undefined, rejecting('broker_unsupported_platform: no transport here (os=windows)'), genId,
    );
    expect(unavailable(a).kind).toBe('broker_unsupported_platform');
    expect(unavailable(a).detail).toContain('os=windows');
  });

  it('a reply that is not a legal result frame is `unavailable`, never upgraded into a verdict', async () => {
    // Something answered — but an illegal frame must not become a decision of either sign.
    const a = await attemptGovernedTurn('conv-1', undefined, resolving({ protocol: 'evil', status: 'committed' }), genId);
    expect(unavailable(a).kind).toBe('malformed_broker_reply');
    expect(isVerified(a)).toBe(false);
  });

  it('a forged trust_state cannot produce a verified outcome — it becomes a non-decision', async () => {
    const forged = committedFrame();
    forged.message.trust_state = 'trusted_verified_lol';
    const a = await attemptGovernedTurn('conv-1', undefined, resolving(forged), genId);
    expect(unavailable(a).kind).toBe('malformed_broker_reply');
    expect(isVerified(a)).toBe(false);
  });

  it('a request that cannot even be built never contacts the broker', async () => {
    let contacted = false;
    const transport: BrokerTransport = async () => { contacted = true; return committedFrame(); };
    const a = await attemptGovernedTurn('conv-1', undefined, transport, () => 'not-a-uuid');
    expect(unavailable(a).kind).toBe('malformed_request');
    expect(contacted).toBe(false);
  });

  it('never rejects — every failure path resolves with an honest outcome', async () => {
    const paths = [
      attemptGovernedTurn('c', undefined, rejecting('anything at all'), genId),
      attemptGovernedTurn('c', undefined, resolving(null), genId),
      attemptGovernedTurn('c', undefined, resolving(blockedFrame('not_a_real_reason')), genId),
    ];
    const settled = await Promise.all(paths);
    for (const a of settled) expect(unavailable(a).kind).toBeTruthy();
  });

  it('sends only the three closed fields, whatever the outcome', async () => {
    let sent: Record<string, unknown> | undefined;
    const transport: BrokerTransport = async (req) => {
      sent = req as unknown as Record<string, unknown>;
      throw new Error('broker_unavailable: nope');
    };
    await attemptGovernedTurn('conv-1', 'agent-x', transport, genId);
    expect(Object.keys(sent ?? {}).sort()).toEqual(['agent', 'client_request_id', 'conversation_id', 'protocol']);
  });
});
