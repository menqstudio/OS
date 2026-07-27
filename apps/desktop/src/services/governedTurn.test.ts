import { describe, it, expect } from 'vitest';
import {
  buildRequest, parseResult, isVerified, runGovernedTurn,
  REQUEST_PROTOCOL, RESULT_PROTOCOL, TRUSTED_VERIFIED,
  type GovernedTurnRequest,
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
  return { protocol: RESULT_PROTOCOL, status: 'blocked', client_request_id: CRID, broker_turn_id: 'bt-1', conversation_id: 'conv-1', reason };
}

describe('renderer governed-turn thin proxy', () => {
  it('builds a request carrying ONLY the three closed fields', () => {
    const req = buildRequest('conv-1', 'agent-x', genId);
    expect(Object.keys(req).sort()).toEqual(['agent', 'client_request_id', 'conversation_id', 'protocol']);
    expect(req.protocol).toBe(REQUEST_PROTOCOL);
    expect(req.client_request_id).toBe(CRID);
    // no system/history/config/hash/nonce/broker_turn_id can leak from the renderer
    expect(req as Record<string, unknown>).not.toHaveProperty('system');
    expect(req as Record<string, unknown>).not.toHaveProperty('broker_turn_id');
  });

  it('omits agent when not provided', () => {
    const req = buildRequest('conv-1', undefined, genId);
    expect(req).not.toHaveProperty('agent');
  });

  it('rejects a non-UUIDv4 client_request_id', () => {
    expect(() => buildRequest('conv-1', undefined, () => 'not-a-uuid')).toThrow();
  });

  it('parses a committed frame into the verified message projection', () => {
    const r = parseResult(committedFrame());
    expect(r.status).toBe('committed');
    if (r.status === 'committed') {
      expect(r.message.body).toBe('hello');
      expect(r.message.role).toBe('assistant');
      expect(r.message.trustState).toBe(TRUSTED_VERIFIED);
    }
    expect(isVerified(r)).toBe(true);
  });

  it('parses a blocked frame into a closed reason with no message', () => {
    const r = parseResult(blockedFrame('turn_in_progress'));
    expect(r.status).toBe('blocked');
    if (r.status === 'blocked') expect(r.reason).toBe('turn_in_progress');
    expect(isVerified(r)).toBe(false);
  });

  it('refuses a committed frame that is not trusted_verified (no forged Verified)', () => {
    const forged = committedFrame();
    forged.message.trust_state = 'forged_verified';
    expect(() => parseResult(forged)).toThrow();
  });

  it('refuses a committed frame whose message role is not assistant', () => {
    const bad = committedFrame();
    (bad.message as Record<string, unknown>).role = 'system';
    expect(() => parseResult(bad)).toThrow();
  });

  it('refuses a blocked frame with an unknown reason', () => {
    expect(() => parseResult(blockedFrame('made_up_reason'))).toThrow();
  });

  it('refuses a blocked frame that carries a message', () => {
    const bad = { ...blockedFrame('malformed'), message: committedFrame().message };
    expect(() => parseResult(bad)).toThrow();
  });

  it('refuses a frame with the wrong protocol', () => {
    const bad = { ...committedFrame(), protocol: 'brops.other.v1' };
    expect(() => parseResult(bad)).toThrow();
  });

  it('runGovernedTurn forwards through the transport and parses the reply', async () => {
    let sent: GovernedTurnRequest | undefined;
    const transport = async (req: GovernedTurnRequest) => { sent = req; return committedFrame(); };
    const r = await runGovernedTurn('conv-1', 'agent-x', transport, genId);
    expect(sent?.client_request_id).toBe(CRID);
    expect(r.status).toBe('committed');
  });
});
