import { describe, it, expect } from 'vitest';
import { buildAssignment, attemptDispatch, type AssignmentInput } from './agentsDispatch';

/**
 * What `agentsDispatch.nolease.test.ts` does NOT prove — sixth independent audit, `A-09`.
 *
 * Its sibling suite is sound about what it tests. Two roadmap rows then cited it as proof that
 * *"the desktop never holds a lease/key"* and stores *"no external secret"*, and it proves neither.
 * The auditor measured three routes straight through it, all with the whitelist exact and the
 * FORBIDDEN sweep silent:
 *
 *   1. an opaque JWT in `rollbackStrategy` — a free-text field `buildAssignment` copies verbatim
 *      into `contract_draft.rollback.strategy`, whose value contains no English keyword;
 *   2. `pubkey` / `apikey` / `keystore` / `sessionkey` — `(?<![a-z])key(?![a-z])` matches none;
 *   3. a `number[]` whose bytes decode to `"lease-7f2a91"` — `flatten()` keeps only strings.
 *
 * **This file asserts that those three still get through, on purpose.** That is not a defect being
 * ratified: it is the boundary of a check being made executable, so nobody reads the suite next to
 * it as a guarantee it was never able to give. The rows now claim what is actually established —
 * the frame shape is fixed, and no lease-shaped WORD travels.
 *
 * # The decision `T-030` asks for, taken here
 *
 * A stronger property is **not testable desktop-side**, and the reason is not effort. A credential
 * is defined by what a remote system will accept, not by anything about its text: an opaque token
 * and a rollback note are the same bytes to this process. The candidate fix — a high-entropy
 * detector — is a heuristic that would fire on legitimate ids, digests and hashes, and a heuristic
 * that reads as proof is worse than the honest gap, because the next roadmap row would cite it too.
 *
 * What CAN be done, and is: fix the frame (done, and mutation-tested next door), keep free-text
 * fields declared as free text, and write the limit down where it cannot rot — which is here,
 * rather than in a comment.
 */

const BASE: AssignmentInput = {
  taskId: 'task-42',
  title: 'Read the ledger',
  objective: 'Summarise the durable ledger without writing to it.',
  mode: 'review',
  risk: 'low',
  packId: 'architecture-audit',
  agentSlug: 'ledger-reader',
  assigneeRole: 'Ledger Reader',
  tier: 'reader',
  scope: ['apps/desktop/src/features'],
  prohibitedScope: ['engine'],
  coreSkills: ['analysis-primary'],
  doneCriteria: ['the ledger is summarised'],
  verifierAgentSlug: null,
  verifierRole: null,
  verificationCommands: [],
  rollbackStrategy: 'nothing was written',
};

const UUID = 'ffffffff-ffff-4fff-8fff-ffffffffffff';

/** The sibling suite's sweep, verbatim, so this file measures the real thing. */
function flatten(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') out.push(value);
  else if (Array.isArray(value)) value.forEach((v) => flatten(v, out));
  else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) { out.push(k); flatten(v, out); }
  }
  return out;
}
const FORBIDDEN = /lease|(?<![a-z])key(?![a-z])|secret|token|nonce|signature|private/i;

async function wire(input: AssignmentInput): Promise<unknown> {
  let sent: unknown = null;
  await attemptDispatch(buildAssignment(input), async (req) => { sent = req; return null; }, () => UUID);
  return sent;
}

describe('the no-lease sweep proves the FRAME, not the absence of a credential', () => {
  it('a control credential IS caught — the sweep is not vacuous', async () => {
    const sent = await wire({ ...BASE, rollbackStrategy: 'lease-should-never-travel' });
    expect(flatten(sent).filter((s) => FORBIDDEN.test(s)).length).toBeGreaterThan(0);
  });

  it('route 1: an opaque token in a free-text field travels, and the sweep is silent', async () => {
    const jwt = 'eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiI3ZjJhOTEifQ.3xR9';
    const sent = await wire({ ...BASE, rollbackStrategy: jwt });
    expect(flatten(sent), 'the value really does reach the wire').toContain(jwt);
    expect(flatten(sent).filter((s) => FORBIDDEN.test(s)),
      'and the sweep has nothing to say about it').toEqual([]);
  });

  it('route 2: the `key` word-boundary matches none of the compound forms', () => {
    for (const word of ['pubkey', 'apikey', 'keystore', 'sessionkey']) {
      expect(FORBIDDEN.test(word), `${word} is not matched`).toBe(false);
    }
    // The bare word is, which is why the pattern looks like it works.
    expect(FORBIDDEN.test('key')).toBe(true);
  });

  it('route 3: a non-string leaf is invisible to a string sweep', async () => {
    const bytes = Array.from('lease-7f2a91').map((c) => c.charCodeAt(0));
    const sent = await wire({ ...BASE, doneCriteria: ['done'], verificationCommands: [] });
    // The sweep only ever sees strings; a numeric array carrying the same characters is dropped.
    expect(flatten({ ...(sent as object), smuggled: bytes })
      .filter((s) => FORBIDDEN.test(s))).toEqual([]);
    expect(String.fromCharCode(...bytes)).toBe('lease-7f2a91');
  });

  it('what IS established: the frame is exactly its declared fields', async () => {
    // Stated positively at the end, because the point of this file is the boundary of a real
    // guarantee, not the absence of one.
    const sent = await wire(BASE) as Record<string, unknown>;
    expect(Object.keys(sent).sort()).toEqual([
      'agent_definition', 'capability_tier', 'client_request_id',
      'contract_draft', 'pack_role_reference', 'protocol',
    ].sort());
  });
});
