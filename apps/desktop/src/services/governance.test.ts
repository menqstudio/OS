import { describe, it, expect } from 'vitest';
import {
  parseGovernanceRead, isMirrored, isBlockedOrUnreachable,
  hasRecords, recordCount, isUnauthenticatedMirror,
  engineEmptyReason, engineSourceKind, engineDoesNotKnowTask,
  type GovernanceSurface,
} from './governance';

const SURFACE: GovernanceSurface = 'verdicts';

describe('parseGovernanceRead — fail-closed governance mirror parse', () => {
  it('parses a well-formed ok reply into a mirrored read', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'ok', surface: 'verdicts', records: [{ id: 'r-1' }] });
    expect(r.state).toBe('ok');
    expect(r.records).toHaveLength(1);
    expect(isMirrored(r)).toBe(true);
    expect(isBlockedOrUnreachable(r)).toBe(false);
  });

  it('passes through a blocked reply with its reason', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'blocked', surface: 'verdicts', reason: 'engine refused' });
    expect(r.state).toBe('blocked');
    expect(r.reason).toBe('engine refused');
    expect(isBlockedOrUnreachable(r)).toBe(true);
  });

  it('passes through an unreachable reply', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'unreachable', surface: 'verdicts', reason: 'broker_unavailable' });
    expect(r.state).toBe('unreachable');
    expect(isMirrored(r)).toBe(false);
  });

  it('degrades an ok reply WITHOUT a records array to blocked (never fabricated ok)', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'ok', surface: 'verdicts' });
    expect(r.state).toBe('blocked');
  });

  it('fails closed to unreachable for a non-object reply', () => {
    expect(parseGovernanceRead(SURFACE, null).state).toBe('unreachable');
    expect(parseGovernanceRead(SURFACE, 'nope').state).toBe('unreachable');
    expect(parseGovernanceRead(SURFACE, 42).state).toBe('unreachable');
  });

  it('fails closed to unreachable for an unknown state (never upgrades to ok)', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'verified', records: [{ id: 'x' }] });
    expect(r.state).toBe('unreachable');
    expect(isMirrored(r)).toBe(false);
  });
});

describe('an ok mirror is not authentication, and empty is not evidence', () => {
  it('defaults `authenticated` to false when the backend does not say otherwise', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'ok', surface: 'verdicts', records: [{ id: 'r-1' }] });
    expect(r.authenticated).toBe(false);
    expect(isUnauthenticatedMirror(r)).toBe(true);
  });

  it('never reads a truthy non-true value as authenticated', () => {
    for (const v of ['true', 1, {}, 'yes']) {
      const r = parseGovernanceRead(SURFACE, {
        state: 'ok', surface: 'verdicts', records: [{ id: 'r-1' }], authenticated: v,
      });
      expect(r.authenticated).toBe(false);
    }
  });

  it('carries a literal authenticated:true through (so a future signature check can flip it)', () => {
    const r = parseGovernanceRead(SURFACE, {
      state: 'ok', surface: 'verdicts', records: [{ id: 'r-1' }], authenticated: true,
    });
    expect(r.authenticated).toBe(true);
    expect(isUnauthenticatedMirror(r)).toBe(false);
  });

  it('reports an ok reply with an EMPTY record set as carrying no records', () => {
    const r = parseGovernanceRead(SURFACE, { state: 'ok', surface: 'verdicts', records: [] });
    // The read succeeded — that is honest — but there is nothing to show, and no page
    // may treat it as satisfied evidence.
    expect(r.state).toBe('ok');
    expect(recordCount(r)).toBe(0);
    expect(hasRecords(r)).toBe(false);
  });

  it('reports no records for blocked / unreachable reads', () => {
    expect(hasRecords(parseGovernanceRead(SURFACE, { state: 'blocked', reason: 'x' }))).toBe(false);
    expect(recordCount(parseGovernanceRead(SURFACE, { state: 'unreachable', reason: 'x' }))).toBe(0);
    expect(isUnauthenticatedMirror(parseGovernanceRead(SURFACE, { state: 'blocked' }))).toBe(false);
  });
});

describe("the engine's own account of an empty surface", () => {
  // The reply the Rust mirror serializes for an empty read: the three-valued `ok`
  // state, plus what the engine said about its own store.
  const EMPTY = {
    state: 'ok',
    surface: 'verdicts',
    records: [],
    authenticated: false,
    engine: {
      emptyReason: 'the orchestration runtime holds no tasks, so nothing has been recorded',
      recordCount: 0,
      knownTask: false,
      sourceKind: 'persisted-verifier-receipts',
    },
  };

  it("carries the engine's reason through the parse, verbatim", () => {
    const r = parseGovernanceRead(SURFACE, EMPTY);
    expect(r.state).toBe('ok');
    expect(engineEmptyReason(r)).toBe(
      'the orchestration runtime holds no tasks, so nothing has been recorded',
    );
    expect(engineDoesNotKnowTask(r)).toBe(true);
    expect(engineSourceKind(r)).toBe('persisted-verifier-receipts');
    expect(r.engine?.recordCount).toBe(0);
  });

  it('never explains emptiness over a set of records', () => {
    // "There is nothing here because ..." must not appear under a list of things.
    const r = parseGovernanceRead(SURFACE, { ...EMPTY, records: [{ id: 'r-1' }] });
    expect(hasRecords(r)).toBe(true);
    expect(engineEmptyReason(r)).toBeNull();
    // The provenance line is still legitimate beside records.
    expect(engineSourceKind(r)).toBe('persisted-verifier-receipts');
  });

  it('never explains emptiness over a refusal', () => {
    // "I could not look" is not "I looked and found nothing" — a blocked read keeps
    // its own `reason` and grows no explanation-of-emptiness.
    const r = parseGovernanceRead(SURFACE, {
      state: 'blocked', surface: 'verdicts', reason: 'BROPS_GOVERNANCE_STATE_DIR is unset',
      engine: { emptyReason: 'the orchestration runtime holds no tasks' },
    });
    expect(r.state).toBe('blocked');
    expect(r.reason).toBe('BROPS_GOVERNANCE_STATE_DIR is unset');
    expect(engineEmptyReason(r)).toBeNull();
    expect(engineSourceKind(r)).toBeNull();
    expect(engineDoesNotKnowTask(r)).toBe(false);
  });

  it('is fail-quiet: a malformed account is absent, never invented', () => {
    const r = parseGovernanceRead(SURFACE, {
      state: 'ok',
      surface: 'verdicts',
      records: [],
      engine: { emptyReason: 42, knownTask: 'yes', sourceKind: '', recordCount: 'many' },
    });
    expect(r.state).toBe('ok');
    expect(r.engine).toBeUndefined();
    expect(engineEmptyReason(r)).toBeNull();
    expect(engineDoesNotKnowTask(r)).toBe(false);
  });

  it("does not let the engine's word about its store raise the mirror's trust", () => {
    // `record_authentication` is the engine vouching for itself; the Rust mirror drops
    // it. Even if something upstream tried to smuggle a claim in beside the account,
    // `authenticated` is decided only by the backend's own literal `true`.
    const r = parseGovernanceRead(SURFACE, {
      state: 'ok',
      surface: 'verdicts',
      records: [{ id: 'r-1' }],
      engine: {
        sourceKind: 'signed-evidence-store',
        recordAuthentication: 'ed25519-signature-verified',
      },
    });
    expect(r.authenticated).toBe(false);
    expect(isUnauthenticatedMirror(r)).toBe(true);
    expect(JSON.stringify(r.engine)).not.toContain('ed25519');
  });
});
