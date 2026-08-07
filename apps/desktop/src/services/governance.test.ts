import { describe, it, expect } from 'vitest';
import {
  parseGovernanceRead, isMirrored, isBlockedOrUnreachable,
  hasRecords, recordCount, isUnauthenticatedMirror,
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
