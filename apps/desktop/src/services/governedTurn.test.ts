import { describe, it, expect } from 'vitest';
import {
  buildRequest, parseResult, isVerified, runGovernedTurn,
  CommitNotAcceptedError, COMMIT_NOT_ACCEPTED_DETAIL, DEMONSTRATION_CUSTODY,
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
    expect(req as unknown as Record<string, unknown>).not.toHaveProperty('system');
    expect(req as unknown as Record<string, unknown>).not.toHaveProperty('broker_turn_id');
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

  // The broker commits `demonstration_custody` on a configured deployment today. The renderer's
  // contract (bridge/contracts/renderer-governed-turn-result.schema.json) accepts only
  // `trusted_verified`, and that refusal is one of the three holding the production gate.
  it('refuses a broker commit under demonstration_custody, and says a real verdict was not accepted here', () => {
    const demo = committedFrame();
    demo.message.trust_state = DEMONSTRATION_CUSTODY;
    let thrown: unknown;
    try { parseResult(demo); } catch (e) { thrown = e; }
    expect(thrown, 'a demonstration_custody commit was ACCEPTED').toBeInstanceOf(CommitNotAcceptedError);
    const refusal = thrown as CommitNotAcceptedError;
    // The message says what happened: a broker verdict existed, and this app declined it.
    expect(refusal.message).toBe(COMMIT_NOT_ACCEPTED_DETAIL);
    expect(refusal.message).toMatch(/a real broker verdict exists/);
    expect(refusal.message).toMatch(/this app does not accept it or display its reply/);
    expect(refusal.message).toMatch(/only trusted_verified is accepted here/);
    // It names the turn and the label — and carries nothing of the reply.
    expect(refusal.trustState).toBe('demonstration_custody');
    expect(refusal.brokerTurnId).toBe('bt-1');
    expect(JSON.stringify({ ...refusal, message: refusal.message })).not.toContain('hello');
    expect(refusal).not.toHaveProperty('body');
  });

  it('the schema the renderer answers to still pins the committed label to trusted_verified alone', async () => {
    // The sentence above is only true while the contract says so. Read the real file.
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const schema = JSON.parse(readFileSync(
      resolve(process.cwd(), '../../bridge/contracts/renderer-governed-turn-result.schema.json'), 'utf8',
    ));
    const committed = schema.oneOf.find((b: { title: string }) => b.title === 'committed');
    const trustState = committed.properties.message.properties.trust_state;
    expect(trustState.const).toBe(TRUSTED_VERIFIED);
    expect(trustState).not.toHaveProperty('enum');
    expect(trustState.description).toMatch(/renderer's acceptance contract, not the broker's emission set/);
  });

  it('a label nobody recognises is NOT described as a broker commit', () => {
    const forged = committedFrame();
    forged.message.trust_state = 'demonstration_custody_lol';
    let thrown: unknown;
    try { parseResult(forged); } catch (e) { thrown = e; }
    expect(thrown).toBeInstanceOf(Error);
    expect(thrown).not.toBeInstanceOf(CommitNotAcceptedError);
    expect((thrown as Error).message).toBe('committed message is not trusted_verified');
  });

  it('an INCOMPLETE frame labelled demonstration_custody is malformed, not a broker commit', () => {
    // Only a complete projection may be called a commit: the shape is read before the label.
    const partial = committedFrame();
    partial.message.trust_state = DEMONSTRATION_CUSTODY;
    delete (partial.message as Record<string, unknown>).body;
    let thrown: unknown;
    try { parseResult(partial); } catch (e) { thrown = e; }
    expect(thrown).toBeInstanceOf(Error);
    expect(thrown).not.toBeInstanceOf(CommitNotAcceptedError);
  });

  it('runGovernedTurn rejects on a demonstration_custody commit — it never resolves with one', async () => {
    const demo = committedFrame();
    demo.message.trust_state = DEMONSTRATION_CUSTODY;
    await expect(runGovernedTurn('conv-1', undefined, () => Promise.resolve(demo), genId))
      .rejects.toBeInstanceOf(CommitNotAcceptedError);
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
