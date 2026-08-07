import { describe, it, expect } from 'vitest';
import type { Integration } from '../domain/entities';
import {
  enablementOf, credentialCustodyOf, verdictOf, isGenuinelyConnected,
  connectorStateOf, summarize, UNTESTED, isAnswered,
  type Reachability,
} from './integrationsModel';

// The state model is the page's honesty boundary: it decides which of four independent
// facts the UI is allowed to assert. These tests pin the fail-closed direction of each
// derivation — every one of them is a test that the model REFUSES to claim something.

const rec = (over: Partial<Integration> = {}): Integration => ({
  id: 'in-1',
  name: 'GitHub',
  provider: 'github',
  status: 'disconnected',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
  ...over,
});

const reachable: Reachability = { state: 'reachable', checkedAt: 'now' };
const unreachable: Reachability = { state: 'unreachable', reason: 'no answer', checkedAt: 'now' };
const unsupported: Reachability = { state: 'unsupported', reason: 'not allowed', checkedAt: 'now' };
const indeterminate: Reachability = { state: 'indeterminate', reason: 'boom', checkedAt: 'now' };

describe('enablement is read from the local record and fails closed', () => {
  it('maps the three statuses the Rust store accepts', () => {
    expect(enablementOf('connected')).toBe('enabled');
    expect(enablementOf('disconnected')).toBe('not_enabled');
    expect(enablementOf('error')).toBe('faulted');
  });

  it('treats any unrecognized status as unknown, never as enabled', () => {
    for (const s of ['', 'CONNECTED', 'connecting', 'ok', 'true', 'active', 'connected ']) {
      expect(enablementOf(s), `status ${JSON.stringify(s)}`).toBe('unknown');
    }
  });
});

describe('credential custody', () => {
  it('reports no reference for the record shape the backend actually sends', () => {
    expect(credentialCustodyOf(rec())).toBe('no_reference');
  });

  it('reports a reference only when the record really carries a non-empty one', () => {
    expect(credentialCustodyOf({ ...rec(), authRef: 'engine:github' } as Integration)).toBe('referenced');
    expect(credentialCustodyOf({ ...rec(), authRef: '   ' } as Integration)).toBe('no_reference');
    expect(credentialCustodyOf({ ...rec(), authRef: 1 } as unknown as Integration)).toBe('no_reference');
  });
});

describe('the verdict can only reach connected_verified through a real check', () => {
  it('is connected_verified only when enabled AND the probe answered reachable', () => {
    expect(verdictOf('enabled', reachable)).toBe('connected_verified');
    expect(isGenuinelyConnected(verdictOf('enabled', reachable))).toBe(true);
  });

  it('never claims connected from the local record alone', () => {
    // This is the defect the page exists to prevent: `status='connected'` is a local
    // write, and on its own it must land in an explicitly unverified state.
    expect(verdictOf('enabled', UNTESTED)).toBe('enabled_unverified');
    expect(isGenuinelyConnected(verdictOf('enabled', UNTESTED))).toBe(false);
  });

  it('never upgrades a probe that could not answer into a connection', () => {
    for (const r of [unsupported, indeterminate]) {
      expect(verdictOf('enabled', r)).toBe('enabled_unverified');
      expect(isGenuinelyConnected(verdictOf('enabled', r))).toBe(false);
    }
  });

  it('reports a real negative answer as unreachable, distinct from "could not ask"', () => {
    expect(verdictOf('enabled', unreachable)).toBe('unreachable');
    expect(verdictOf('enabled', unsupported)).not.toBe('unreachable');
  });

  it('lets a recorded fault or an unrecognized status outrank any probe result', () => {
    expect(verdictOf('faulted', reachable)).toBe('faulted');
    expect(verdictOf('unknown', reachable)).toBe('unknown');
    expect(verdictOf('not_enabled', reachable)).toBe('not_enabled');
    expect(isGenuinelyConnected(verdictOf('unknown', reachable))).toBe(false);
  });
});

describe('isAnswered', () => {
  it('is true only for a probe that really got an answer either way', () => {
    expect(isAnswered(reachable)).toBe(true);
    expect(isAnswered(unreachable)).toBe(true);
    expect(isAnswered(UNTESTED)).toBe(false);
    expect(isAnswered(unsupported)).toBe(false);
    expect(isAnswered(indeterminate)).toBe(false);
  });
});

describe('page telemetry counts what is true, not what was asked for', () => {
  const states = [
    connectorStateOf(rec({ id: 'a', status: 'connected' }), UNTESTED),
    connectorStateOf(rec({ id: 'b', status: 'connected' }), reachable),
    connectorStateOf(rec({ id: 'c', status: 'connected' }), unreachable),
    connectorStateOf(rec({ id: 'd', status: 'disconnected' }), UNTESTED),
    connectorStateOf(rec({ id: 'e', status: 'error' }), UNTESTED),
    connectorStateOf(rec({ id: 'f', status: 'weird' }), UNTESTED),
  ];

  it('keeps "enabled" and "verified" as separate numbers', () => {
    const t = summarize(states);
    expect(t.total).toBe(6);
    expect(t.enabled).toBe(3);
    expect(t.verifiedConnected).toBe(1);
    expect(t.enabledUnverified).toBe(1);
    expect(t.unreachable).toBe(1);
    expect(t.faulted).toBe(1);
    expect(t.notEnabled).toBe(1);
    expect(t.unknownStatus).toBe(1);
    expect(t.untested).toBe(4);
  });

  it('drives the live indicator from verified only — enabled alone never lights it', () => {
    const enabledOnly = [connectorStateOf(rec({ status: 'connected' }), UNTESTED)];
    expect(summarize(enabledOnly).enabled).toBe(1);
    expect(summarize(enabledOnly).anyVerifiedConnected).toBe(false);
    expect(summarize(states).anyVerifiedConnected).toBe(true);
    expect(summarize([]).anyVerifiedConnected).toBe(false);
  });
});
