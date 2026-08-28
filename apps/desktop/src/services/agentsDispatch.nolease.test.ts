import { describe, it, expect, vi } from 'vitest';
// The service imports `hasBackend` from desktop.ts, which pulls in the Tauri core module.
// Mock that boundary so this stays a pure unit test — the dispatch transport is injected.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: () => Promise.resolve(null),
  Channel: class {},
}));

import {
  attemptDispatch, buildAssignment, parseDispatchReply,
  DISPATCH_REQUEST_PROTOCOL, DISPATCH_RESULT_PROTOCOL,
  type Assignment, type AssignmentInput, type DispatchOutcome,
} from './agentsDispatch';

/**
 * Phase 6's stop condition, as a test: **"If fan-out tempts the desktop to hold/relay a lease →
 * stop (that breaks the whole model)."** Its Definition of Done asks for the contract test
 * directly — *"Desktop never holds a lease/key (contract test green)"* — and its CI requirement
 * spells out the shape: *"a test asserts the desktop never serializes a lease/key."*
 *
 * There was one for the governance READ commands, in `governance.rs`, inspecting the Tauri
 * command signatures. There was none for **dispatch**, which is the surface the stop condition
 * is actually about: dispatch is where a lease exists, where fan-out happens, and where relaying
 * one would be a plausible-looking convenience.
 *
 * The model this protects: the engine issues a single-use lease **into** each builder. The
 * desktop observes many governed builders and holds nothing. An accepted reply names a
 * `lease_id` — that is EVIDENCE the assignment was governed, and the parser refuses an accepted
 * frame without one — but naming a lease and holding one are different acts, and the direction
 * of travel is the whole distinction. This asserts the direction.
 */

const SHA256 = 'a'.repeat(64);
const SHA1 = 'b'.repeat(40);
const UUID = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

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

const assignment = (): Assignment => buildAssignment(BASE);

/**
 * Every string that appears anywhere in a value, however deeply nested.
 *
 * **Non-string leaves are visited too** (sixth audit `A-09` route 3, reopened by the eighth).
 * The earlier version pushed only `typeof value === 'string'`, so a `number[]` whose elements
 * are character codes decoded to `"lease-7f2a91"` on the far side while being invisible here.
 * Numbers and booleans are now stringified, and an array's printable character codes are
 * additionally pushed in decoded form — the sweep sees the bytes as the text they would become,
 * not as digits. The decode survives one out-of-range byte (ninth audit `I-03`).
 */
function flatten(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') out.push(value);
  else if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    out.push(String(value));
  } else if (Array.isArray(value)) {
    out.push(...decodeCharCodeRuns(value));
    value.forEach((v) => flatten(v, out));
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) { out.push(k); flatten(v, out); }
  }
  return out;
}

/**
 * The printable text a character-code array carries — ninth audit `I-03`.
 *
 * The superseded form returned `null` for the whole array the moment ONE element fell outside
 * `0x20`–`0x7e`, so a newline appended to the character-code array made it invisible again. Two
 * things are produced instead: every maximal printable RUN, so adjacency is preserved, and the
 * concatenation of all printable bytes with the non-printable ones removed, so a value interleaved
 * with separators cannot hide either. An array with no printable byte yields nothing at all, which
 * is what keeps the decode from becoming a wildcard that invents offenders.
 */
function decodeCharCodeRuns(list: readonly unknown[]): string[] {
  const out: string[] = [];
  let run = '';
  let all = '';
  for (const v of list) {
    if (typeof v === 'number' && Number.isInteger(v) && v >= 0x20 && v <= 0x7e) {
      run += String.fromCharCode(v);
      all += String.fromCharCode(v);
    } else if (run) {
      out.push(run);
      run = '';
    }
  }
  if (run) out.push(run);
  if (all && !out.includes(all)) out.push(all);
  return out;
}

/**
 * The credential-shaped vocabulary. `key` carries a **compound** family rather than the bare
 * word: `(?<![a-z])key(?![a-z])` matched none of `pubkey` / `apikey` / `keystore` / `sessionkey`
 * (sixth audit `A-09` route 2, reopened by the eighth), while still needing to leave `monkey`,
 * `turkey` and `keyboard` alone — a lookaround that admits every compound would fire on ordinary
 * prose, and a sweep that cries wolf gets deleted. The prefix and suffix groups are both optional,
 * so the bare-word behaviour this replaced is preserved exactly.
 */
const FORBIDDEN =
  /lease|secret|token|nonce|signature|private|(?<![a-z])(?:pub|api|access|secret|private|public|session|signing|host|ssh|gpg|master|root|enc|dec)?[-_ ]?keys?(?:tore|chain|file|pair|ring|id)?(?![a-z])/i;

describe('dispatch — the desktop never serializes a lease or a key', () => {
  it('the request frame carries no lease, key, token, nonce or signature — at any depth', async () => {
    let sent: unknown = null;
    await attemptDispatch(assignment(), async (req) => { sent = req; return null; }, () => UUID);

    expect(sent).not.toBeNull();
    const offenders = flatten(sent).filter((s) => FORBIDDEN.test(s));
    expect(offenders).toEqual([]);
  });

  it('the frame is exactly the five declared fields — extra keys cannot ride along', async () => {
    let sent: Record<string, unknown> = {};
    await attemptDispatch(assignment(), async (req) => {
      sent = req as unknown as Record<string, unknown>; return null;
    }, () => UUID);

    // A whitelist, not a blacklist. A blacklist protects against the names we thought of; this
    // fails the moment ANY new field appears, which is when a reviewer should look.
    expect(Object.keys(sent).sort()).toEqual([
      'agent_definition', 'capability_tier', 'client_request_id',
      'contract_draft', 'pack_role_reference', 'protocol',
    ].sort());
    expect(sent.protocol).toBe(DISPATCH_REQUEST_PROTOCOL);
  });

  it('a lease smuggled into the assignment does not reach the wire', async () => {
    // The renderer builds the frame field by field rather than spreading the assignment, so an
    // attacker-controlled or careless extra property on the draft is simply not copied. This is
    // the test that fails if someone "simplifies" the builder into a spread.
    const poisoned = assignment() as unknown as Record<string, unknown>;
    (poisoned as Record<string, unknown>).lease_id = 'lease-should-never-travel';
    (poisoned.grant as Record<string, unknown>).key_id = 'key-should-never-travel';

    let sent: unknown = null;
    await attemptDispatch(poisoned as unknown as Assignment,
      async (req) => { sent = req; return null; }, () => UUID);

    const wire = JSON.stringify(sent ?? {});
    expect(wire).not.toContain('lease-should-never-travel');
    expect(wire).not.toContain('key-should-never-travel');
  });

  it('an accepted reply’s lease_id is READ, and is never echoed into a later request', async () => {
    const accepted = {
      protocol: DISPATCH_RESULT_PROTOCOL,
      client_request_id: UUID,
      status: 'accepted',
      assignment_id: 'asg-1',
      contract_digest: SHA256,
      lease_id: 'lease-from-the-engine',
      repository: {
        full_name: 'menqstudio/OS', branch: 'main', worktree: '/w',
        base_commit: SHA1, tree_identity: SHA256,
      },
    };
    const out: DispatchOutcome = parseDispatchReply(accepted);
    expect(out.state).toBe('accepted');
    // Reading it is the point — an accepted frame WITHOUT one is refused, because an assignment
    // with no lease was not governed.
    expect(out).toMatchObject({ leaseId: 'lease-from-the-engine' });

    // …and the next dispatch is built from the assignment alone, so nothing from the previous
    // reply can travel back out.
    let sent: unknown = null;
    await attemptDispatch(assignment(), async (req) => { sent = req; return null; }, () => UUID);
    expect(JSON.stringify(sent ?? {})).not.toContain('lease-from-the-engine');
  });

  it('a refused dispatch still sends nothing sensitive — the failure path is not a loophole', async () => {
    let sent: unknown = null;
    await attemptDispatch(assignment(), async (req) => {
      sent = req;
      return {
        protocol: DISPATCH_RESULT_PROTOCOL, client_request_id: UUID,
        status: 'refused', reason: 'no_lease',
      };
    }, () => UUID);
    expect(flatten(sent).filter((s) => FORBIDDEN.test(s))).toEqual([]);
  });

  it('positive control: the frame really does carry the contract, so the sweep is not vacuous', async () => {
    let sent: unknown = null;
    await attemptDispatch(assignment(), async (req) => { sent = req; return null; }, () => UUID);
    // If this ever fails, the assertions above are passing over an empty object.
    expect(flatten(sent)).toContain('Read the ledger');
  });

  it('`I-03`: one byte outside the printable range no longer defeats the decode', () => {
    // The ninth audit escaped route 3's fix by appending 0x0a: the all-or-nothing decode returned
    // null for the whole array and the sweep went silent again. Both escapes are pinned here, in
    // this copy of the sweep as well as in the boundary suite, because a fix applied to one of
    // three copies is a fix in one of three places.
    const codes = Array.from('lease-7f2a91').map((c) => c.charCodeAt(0));
    const trailing = [...codes, 0x0a];
    const interleaved = codes.flatMap((c) => [c, 0x0a]);
    for (const bytes of [codes, trailing, interleaved]) {
      expect(flatten({ smuggled: bytes })).toContain('lease-7f2a91');
      expect(flatten({ smuggled: bytes }).filter((s) => FORBIDDEN.test(s)).length)
        .toBeGreaterThan(0);
    }
    // And still not a wildcard: an array with no printable byte decodes to nothing.
    expect(decodeCharCodeRuns([1, 2, 3, 999])).toEqual([]);
  });
});
