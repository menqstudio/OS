import { describe, it, expect, vi } from 'vitest';

// The probe module imports Tauri's `invoke` for its default transport. These tests
// always inject a transport, so the real IPC is never touched — the mock only keeps
// the import from exploding in jsdom.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: () => Promise.reject(new Error('no tauri in tests')),
  Channel: class {},
}));

import {
  probeIntegration, declareIntegration, parseProbeReply, parseDeclareReply,
  isCapabilityRefusal, PROBE_COMMAND, DECLARE_COMMAND,
} from './integrationsProbe';

const AT = '2026-01-01T00:00:00.000Z';
const now = () => AT;

/** The verbatim shape of Tauri's capability wall refusal (see Knowledge.delete.test.tsx,
 *  Library.delete.test.tsx — the same string those suites pin for denied commands). */
const CAPABILITY_DENIAL =
  `${PROBE_COMMAND} not allowed. Permissions associated with this command: `;

describe('classifying a rejection: "we could not ask" vs "it did not answer"', () => {
  it('recognizes the capability wall and a missing command', () => {
    expect(isCapabilityRefusal(CAPABILITY_DENIAL)).toBe(true);
    expect(isCapabilityRefusal(`Command ${PROBE_COMMAND} not found`)).toBe(true);
    expect(isCapabilityRefusal('unknown command')).toBe(true);
  });

  it('does not claim a plain transport failure is a missing feature', () => {
    expect(isCapabilityRefusal('socket hang up')).toBe(false);
    expect(isCapabilityRefusal('timed out after 5s')).toBe(false);
  });
});

describe('parseProbeReply refuses to invent a connection', () => {
  it('accepts ONLY a literal boolean true as reachable', () => {
    expect(parseProbeReply({ reachable: true }, AT).state).toBe('reachable');
    // Every one of these is a shape that would otherwise paint a green badge for free.
    for (const bad of ['true', 1, 'yes', {}, [], 'ok']) {
      expect(parseProbeReply({ reachable: bad }, AT).state, JSON.stringify(bad)).toBe('indeterminate');
    }
  });

  it('records an explicit negative as unreachable, with the backend detail', () => {
    const r = parseProbeReply({ reachable: false, detail: 'TLS handshake failed' }, AT);
    expect(r.state).toBe('unreachable');
    expect(r.reason).toBe('TLS handshake failed');
    expect(r.checkedAt).toBe(AT);
  });

  it('supplies an honest reason when the backend gives none', () => {
    expect(parseProbeReply({ reachable: false }, AT).reason).toMatch(/did not answer/);
  });

  it('degrades a non-object or fieldless reply to indeterminate, never reachable', () => {
    for (const raw of [null, undefined, 'reachable', 42, {}, { detail: 'hi' }]) {
      expect(parseProbeReply(raw, AT).state, String(raw)).toBe('indeterminate');
    }
  });

  it('carries the backend detail through on success without upgrading anything else', () => {
    const r = parseProbeReply({ reachable: true, detail: 'HTTP 200' }, AT);
    expect(r).toEqual({ state: 'reachable', reason: 'HTTP 200', checkedAt: AT });
  });
});

describe('probeIntegration never throws and never over-claims', () => {
  it('asks the backend for exactly the connector id', async () => {
    const transport = vi.fn().mockResolvedValue({ reachable: true });
    const r = await probeIntegration('in-1', { transport, now });
    expect(transport).toHaveBeenCalledWith(PROBE_COMMAND, { id: 'in-1' });
    expect(r.state).toBe('reachable');
  });

  it('reports the capability wall as unsupported — a fact about this build', async () => {
    const transport = vi.fn().mockRejectedValue(new Error(CAPABILITY_DENIAL));
    const r = await probeIntegration('in-1', { transport, now });
    // NOT 'unreachable': the connector was never contacted, so nothing may be said
    // about it. The verbatim refusal is preserved so the owner can act on it.
    expect(r.state).toBe('unsupported');
    expect(r.reason).toBe(CAPABILITY_DENIAL);
    expect(r.checkedAt).toBe(AT);
  });

  it('reports an unclassified failure as indeterminate, not as a dead service', async () => {
    const transport = vi.fn().mockRejectedValue(new Error('socket hang up'));
    const r = await probeIntegration('in-1', { transport, now });
    expect(r.state).toBe('indeterminate');
    expect(r.reason).toBe('socket hang up');
  });

  it('survives a non-Error rejection', async () => {
    const transport = vi.fn().mockRejectedValue('plain string boom');
    const r = await probeIntegration('in-1', { transport, now });
    expect(r.state).toBe('indeterminate');
    expect(r.reason).toBe('plain string boom');
  });
});

describe('parseDeclareReply refuses to invent a connector row', () => {
  const full = {
    id: 'in-9', name: 'Slack', provider: 'slack', status: 'disconnected',
    createdAt: '1700000000000', updatedAt: '1700000000000',
  };

  it('accepts a complete record', () => {
    expect(parseDeclareReply(full)).toEqual({ ok: true, integration: full });
  });

  it('refuses a partial or wrongly-typed record', () => {
    for (const key of ['id', 'name', 'provider', 'status', 'createdAt', 'updatedAt']) {
      const partial: Record<string, unknown> = { ...full };
      delete partial[key];
      const out = parseDeclareReply(partial);
      expect(out.ok, `missing ${key}`).toBe(false);
    }
    expect(parseDeclareReply({ ...full, id: 7 }).ok).toBe(false);
    expect(parseDeclareReply('ok').ok).toBe(false);
    expect(parseDeclareReply(null).ok).toBe(false);
  });
});

describe('declareIntegration', () => {
  it('rejects empty input locally, without calling the backend', async () => {
    const transport = vi.fn();
    const a = await declareIntegration('  ', 'github', { transport });
    const b = await declareIntegration('GitHub', '   ', { transport });
    expect(a).toEqual({ ok: false, kind: 'invalid', reason: 'name is required' });
    expect(b).toEqual({ ok: false, kind: 'invalid', reason: 'provider is required' });
    expect(transport).not.toHaveBeenCalled();
  });

  it('sends trimmed values and never a credential field', async () => {
    const transport = vi.fn().mockResolvedValue({
      id: 'in-9', name: 'Slack', provider: 'slack', status: 'disconnected',
      createdAt: '1', updatedAt: '1',
    });
    const out = await declareIntegration('  Slack ', ' slack ', { transport });
    expect(transport).toHaveBeenCalledWith(DECLARE_COMMAND, { name: 'Slack', provider: 'slack' });
    // The whole argument object is pinned: a declaration carries a name and a provider,
    // and there is nowhere for a secret to travel.
    expect(Object.keys(transport.mock.calls[0][1])).toEqual(['name', 'provider']);
    expect(out.ok).toBe(true);
  });

  it('separates "this build cannot" from "the backend said no"', async () => {
    const denied = vi.fn().mockRejectedValue(
      new Error(`${DECLARE_COMMAND} not allowed. Permissions associated with this command: `),
    );
    const refused = vi.fn().mockRejectedValue(new Error('registry is read-only'));
    expect(await declareIntegration('X', 'x', { transport: denied }))
      .toMatchObject({ ok: false, kind: 'unsupported' });
    expect(await declareIntegration('X', 'x', { transport: refused }))
      .toMatchObject({ ok: false, kind: 'refused', reason: 'registry is read-only' });
  });

  it('refuses a success reply that is not a real record', async () => {
    const transport = vi.fn().mockResolvedValue({ ok: true });
    expect(await declareIntegration('X', 'x', { transport }))
      .toMatchObject({ ok: false, kind: 'refused' });
  });
});
