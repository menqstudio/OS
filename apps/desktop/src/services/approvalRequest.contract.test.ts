// The contract test Phase 2 asked for, on the renderer's side of the wall.
//
// `docs/roadmap/phase-2.md` lists it under Tests: "a contract test that a desktop approval-request never
// carries a key/lease". It was unwritable until this path existed -- a test asserting that a nonexistent
// request carries no key is a check that cannot fail, which is the shape this repository deletes rather
// than ships. The Rust half (`brops_core::approval_request`) holds the DOCUMENT to the contract's twelve
// fields; this holds the renderer to the six inputs it may supply and to what it may believe coming back.
//
// The load-bearing assertion of the file is the last one: an outcome claiming a decision is BLOCKED, not
// rendered. Only an owner-signed control-room command adjudicates an approval, and the cockpit must not
// be able to show one that nobody signed.

import { describe, it, expect, vi, beforeEach } from 'vitest';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { desktop } from './desktop';
import { parseApprovalRequestOutcome, REQUESTABLE_COMMANDS } from './approvalRequest';

beforeEach(() => {
  invokeMock.mockReset();
});

const ASK = {
  taskId: 'task-0001',
  requestedCommand: 'approve' as const,
  expectedTaskState: 'awaiting-owner-approval',
  reason: 'the cockpit operator asks the owner to approve this task',
  requestedBy: 'gev@cockpit',
};

function recorded(extra: Record<string, unknown> = {}) {
  return {
    state: 'recorded',
    request_id: 'req-7f2a91c4',
    sequence: 1,
    entry_sha256: 'a'.repeat(64),
    duplicate: false,
    adjudicated: false,
    note: 'recorded, not adjudicated',
    ...extra,
  };
}

describe('a desktop approval-request never carries a key or a lease', () => {
  it('sends exactly the six declared inputs and nothing else', async () => {
    invokeMock.mockResolvedValue(recorded());
    await desktop.requestEngineApproval(ASK);
    expect(invokeMock).toHaveBeenCalledTimes(1);
    const [command, args] = invokeMock.mock.calls[0];
    expect(command).toBe('request_engine_approval');
    expect(Object.keys(args as object).sort()).toEqual([
      'evidenceRefs',
      'expectedTaskState',
      'reason',
      'requestedBy',
      'requestedCommand',
      'taskId',
    ]);
  });

  it('carries no field named after anything that may not cross', async () => {
    invokeMock.mockResolvedValue(recorded());
    await desktop.requestEngineApproval({ ...ASK, evidenceRefs: ['ev-1'] });
    const serialised = JSON.stringify(invokeMock.mock.calls[0][1]).toLowerCase();
    for (const word of [
      'key', 'signature', 'nonce', 'lease', 'verdict', 'secret', 'token', 'credential',
      'password', 'private',
    ]) {
      expect(serialised).not.toContain(word);
    }
  });

  it('asks for one of the three approvals and never a command', () => {
    expect([...REQUESTABLE_COMMANDS]).toEqual(['approve', 'deny', 'request-verification']);
    for (const verb of ['cancel', 'retry', 'reassign']) {
      expect([...REQUESTABLE_COMMANDS]).not.toContain(verb);
    }
  });
});

describe('what the renderer may believe coming back', () => {
  it('a complete record is recorded, and carries the unadjudicated flag through', async () => {
    invokeMock.mockResolvedValue(recorded({ duplicate: true, sequence: 3 }));
    const out = await desktop.requestEngineApproval(ASK);
    expect(out).toEqual({
      state: 'recorded',
      requestId: 'req-7f2a91c4',
      sequence: 3,
      entrySha256: 'a'.repeat(64),
      duplicate: true,
      adjudicated: false,
      note: 'recorded, not adjudicated',
    });
  });

  it("the engine's own no is refused, not blocked", async () => {
    invokeMock.mockResolvedValue({ state: 'refused', reason: "the engine has no task 'task-9999'" });
    const out = await desktop.requestEngineApproval(ASK);
    expect(out.state).toBe('refused');
    expect(out).toHaveProperty('reason', "the engine has no task 'task-9999'");
  });

  it('a transport failure is blocked and never a silent success', async () => {
    invokeMock.mockRejectedValue(new Error('the sidecar did not start'));
    const out = await desktop.requestEngineApproval(ASK);
    expect(out).toEqual({ state: 'blocked', reason: 'the sidecar did not start' });
  });

  it('a record missing its digest or sequence is blocked', () => {
    for (const bad of [{ entry_sha256: 'abc' }, { sequence: 0 }, { sequence: 1.5 }]) {
      expect(parseApprovalRequestOutcome(recorded(bad)).state).toBe('blocked');
    }
  });

  it('a record that does not say adjudicated:false is blocked', () => {
    for (const bad of [{ adjudicated: true }, { adjudicated: 'no' }, { adjudicated: undefined }]) {
      expect(parseApprovalRequestOutcome(recorded(bad)).state).toBe('blocked');
    }
  });

  it('AN OUTCOME CLAIMING A DECISION IS BLOCKED, whatever else it says', () => {
    for (const word of ['granted', 'disposition', 'verdict', 'decision', 'approved']) {
      const out = parseApprovalRequestOutcome(recorded({ [word]: true }));
      expect(out.state).toBe('blocked');
      expect(out).toHaveProperty('reason', expect.stringContaining(word));
    }
  });

  it('an unknown state is blocked rather than guessed at', () => {
    for (const raw of [null, 7, 'recorded', {}, { state: 'ok' }]) {
      expect(parseApprovalRequestOutcome(raw).state).toBe('blocked');
    }
  });
});
