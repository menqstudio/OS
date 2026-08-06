import { describe, it, expect } from 'vitest';
import {
  parseGovernanceRead, isMirrored, isBlockedOrUnreachable,
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
