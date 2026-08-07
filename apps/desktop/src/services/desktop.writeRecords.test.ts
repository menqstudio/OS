// The renderer boundary for two surfaces whose backends existed but which no command and
// no wrapper could reach: the local write records for memory/knowledge, and declaring a
// connector.
//
// Registered-and-unwrapped is the exact defect this wave keeps finding, so these specs pin
// reachability (the right command, with the right arguments) AND honesty (a state is
// passed through verbatim — never upgraded, never softened, and never renamed into the
// vocabulary of the governed receipt path, which is a strictly stronger guarantee).

import { describe, it, expect, vi, beforeEach } from 'vitest';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { desktop, type WriteRecord, type WriteRecordState } from './desktop';

beforeEach(() => {
  invokeMock.mockReset();
});

const record: WriteRecord = {
  id: 'wr-1',
  seq: 1,
  subjectKind: 'memory_entry',
  subjectId: 'm-1',
  operation: 'created',
  contentSha256: 'a'.repeat(64),
  prevRecordSha256: '0'.repeat(64),
  recordSha256: 'b'.repeat(64),
  recordedAt: '2026-08-07T00:00:00Z',
};

describe('local write records are reachable from the renderer', () => {
  it('memory state and history call their own commands with the subject id', async () => {
    invokeMock.mockResolvedValue({ state: 'unrecorded' });
    await desktop.memoryWriteRecordState('m-1');
    expect(invokeMock).toHaveBeenCalledWith('memory_write_record_state', { id: 'm-1' });

    invokeMock.mockResolvedValue([record]);
    await desktop.memoryWriteRecords('m-1');
    expect(invokeMock).toHaveBeenLastCalledWith('memory_write_records', { id: 'm-1' });
  });

  it('knowledge reads the knowledge commands — not the memory ones', async () => {
    invokeMock.mockResolvedValue({ state: 'unrecorded' });
    await desktop.knowledgeWriteRecordState('k-1');
    expect(invokeMock).toHaveBeenCalledWith('knowledge_write_record_state', { id: 'k-1' });

    invokeMock.mockResolvedValue([]);
    await desktop.knowledgeWriteRecords('k-1');
    expect(invokeMock).toHaveBeenLastCalledWith('knowledge_write_records', { id: 'k-1' });

    // Two different subjects share one ledger table; reading one must never be reading
    // the other, or a note would inherit an entry's record.
    expect(invokeMock).not.toHaveBeenCalledWith('memory_write_record_state', expect.anything());
    expect(invokeMock).not.toHaveBeenCalledWith('memory_write_records', expect.anything());
  });

  it('every state the backend can report survives the boundary unchanged', async () => {
    const states: WriteRecordState[] = [
      { state: 'recorded', record },
      { state: 'content_diverged', record, actual_content_sha256: 'c'.repeat(64) },
      { state: 'deleted_but_present', record },
      { state: 'unrecorded' },
    ];
    for (const s of states) {
      invokeMock.mockResolvedValue(s);
      expect(await desktop.memoryWriteRecordState('m-1')).toEqual(s);
    }
  });

  it('a diverged row is never softened into a recorded one', async () => {
    const diverged = {
      state: 'content_diverged',
      record,
      actual_content_sha256: 'c'.repeat(64),
    };
    invokeMock.mockResolvedValue(diverged);
    const got = await desktop.knowledgeWriteRecordState('k-1');
    expect(got.state).toBe('content_diverged');
    // The tamper signal keeps the actual digest, so the UI can show what the row hashes to
    // now versus what was recorded.
    expect(got).toHaveProperty('actual_content_sha256', 'c'.repeat(64));
  });

  it('the vocabulary is the weaker one: nothing on this path reports "verified"', async () => {
    // The states are exactly the four the backend can defend. `verified`/`trusted_verified`
    // belong to the governed receipt path, which holds a key and custody; this one holds
    // neither, so it must never be able to produce those words.
    const reported = new Set<string>();
    for (const s of [
      { state: 'recorded', record },
      { state: 'content_diverged', record, actual_content_sha256: 'c'.repeat(64) },
      { state: 'deleted_but_present', record },
      { state: 'unrecorded' },
    ]) {
      invokeMock.mockResolvedValue(s);
      reported.add((await desktop.memoryWriteRecordState('m-1')).state);
    }
    expect([...reported].sort()).toEqual([
      'content_diverged', 'deleted_but_present', 'recorded', 'unrecorded',
    ]);
    for (const s of reported) expect(s).not.toMatch(/verif/i);
  });

  it('a rejected read rejects — a missing record is a state, an unreadable one is not', async () => {
    invokeMock.mockRejectedValue(new Error('not found: m-404'));
    await expect(desktop.memoryWriteRecordState('m-404')).rejects.toThrow('not found');
  });
});

describe('declaring a connector', () => {
  it('createIntegration invokes the real command with name and provider', async () => {
    const integration = {
      id: 'in-1', name: 'Slack', provider: 'slack',
      status: 'disconnected', createdAt: 'now', updatedAt: 'now',
    };
    invokeMock.mockResolvedValue(integration);
    expect(await desktop.createIntegration('Slack', 'slack')).toEqual(integration);
    expect(invokeMock).toHaveBeenCalledWith('create_integration', { name: 'Slack', provider: 'slack' });
  });

  it('sends no credential field — the desktop holds no secret, so there is nothing to send', async () => {
    invokeMock.mockResolvedValue({
      id: 'in-2', name: 'Notion', provider: 'notion',
      status: 'disconnected', createdAt: 'now', updatedAt: 'now',
    });
    await desktop.createIntegration('Notion', 'notion');
    const [, args] = invokeMock.mock.calls[0] as [string, Record<string, unknown>];
    expect(Object.keys(args).sort()).toEqual(['name', 'provider']);
  });

  it('a newly declared connector is disconnected: declaring is not connecting', async () => {
    invokeMock.mockResolvedValue({
      id: 'in-3', name: 'GitHub', provider: 'github',
      status: 'disconnected', createdAt: 'now', updatedAt: 'now',
    });
    const created = await desktop.createIntegration('GitHub', 'github');
    expect(created.status).toBe('disconnected');
  });
});
