import { describe, it, expect } from 'vitest';
import {
  buildAssignment, attemptDispatch, isContractId, isRepoPath, isWorkPath,
  CAPABILITY_TIERS, CONTRACT_SCHEMA_VERSION, DISPATCH_REQUEST_PROTOCOL, MODES, RISKS,
  type AssignmentInput,
} from './agentsDispatch';

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
 *   2. `pubkey` / `apikey` / `keystore` / `sessionkey` — `(?<![a-z])key(?![a-z])` matched none;
 *   3. a `number[]` whose bytes decode to `"lease-7f2a91"` — `flatten()` kept only strings.
 *
 * **Routes 2 and 3 are now CLOSED, and route 1 is not.** The eighth audit reopened `A-09` with the
 * correct reason: the previous round corrected the two roadmap sentences and made the limit
 * executable, and then marked the finding Done. *Correcting a claim is not closing a finding.* The
 * two halves that were always free — a compound-aware `key` family, and a `flatten` that visits
 * non-string leaves and decodes character-code arrays — are done here, each with the mutant that
 * proves it (revert either and a test below goes red).
 *
 * # Route 1, and the decision `T-030` asks for
 *
 * Route 1 stays open and this file still asserts it, on purpose. A credential is defined by what a
 * remote system will accept, not by anything about its text: an opaque token and a rollback note are
 * the same bytes to this process. The candidate fix — a high-entropy detector — is a heuristic that
 * would fire on legitimate ids, digests and hashes, and a heuristic that reads as proof is worse than
 * the honest gap, because the next roadmap row would cite it too. A declared *grammar* for the
 * free-text fields fails the same way from the other side: tight enough to exclude a JWT also excludes
 * a commit sha, a path, a URL and an Armenian sentence; loose enough for prose admits a token by
 * adding a space.
 *
 * **What IS newly established instead, and it is not a heuristic:** the set of fields whose value is
 * unconstrained is itself *declared and bounded*. Every leaf the frame carries is either
 * shape-constrained (an enum, a contract id, a UUIDv4, a repo path, a const) against its real
 * validator, or named in `DECLARED_FREE_TEXT` with the reason it must stay prose. A new field —
 * the way route 1 would widen — turns this file red rather than travelling silently beside a suite
 * that reads as a guarantee.
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

/**
 * Every string that appears anywhere in a value, however deeply nested.
 *
 * **Non-string leaves are visited too** (sixth audit `A-09` route 3, reopened by the eighth).
 * The earlier version pushed only `typeof value === 'string'`, so a `number[]` whose elements
 * are character codes decoded to `"lease-7f2a91"` on the far side while being invisible here.
 * Numbers and booleans are now stringified, and an array that is *entirely* printable character
 * codes is additionally pushed in its decoded form — the sweep sees the bytes as the text they
 * would become, not as digits.
 */
function flatten(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') out.push(value);
  else if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    out.push(String(value));
  } else if (Array.isArray(value)) {
    const decoded = decodeCharCodes(value);
    if (decoded !== null) out.push(decoded);
    value.forEach((v) => flatten(v, out));
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) { out.push(k); flatten(v, out); }
  }
  return out;
}

/** `[108,101,97,115,101]` → `"lease"`; `null` when the array is not all printable ASCII codes. */
function decodeCharCodes(list: readonly unknown[]): string | null {
  if (list.length === 0) return null;
  const codes: number[] = [];
  for (const v of list) {
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 0x20 || v > 0x7e) return null;
    codes.push(v);
  }
  return String.fromCharCode(...codes);
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

/** Every scalar leaf the frame carries, as `dotted.path` → value. Arrays collapse to their path. */
function leafPaths(value: unknown, prefix = '', out: Array<{ path: string; value: unknown }> = []) {
  if (Array.isArray(value)) { value.forEach((v) => leafPaths(v, prefix, out)); return out; }
  if (value !== null && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) leafPaths(v, prefix ? `${prefix}.${k}` : k, out);
    return out;
  }
  if (value === null) return out;          // an explicit absence carries nothing
  out.push({ path: prefix, value });
  return out;
}

const isStr = (v: unknown): v is string => typeof v === 'string';
const matches = (re: RegExp) => (v: unknown) => isStr(v) && re.test(v);
const oneOf = (...allowed: readonly string[]) => (v: unknown) => isStr(v) && allowed.includes(v);

/**
 * The value shape of every constrained leaf, checked against the module's OWN validators rather
 * than a second copy of them — a private regex here would drift from the one the product enforces.
 */
const SHAPE_CONSTRAINED: Record<string, (v: unknown) => boolean> = {
  'protocol': oneOf(DISPATCH_REQUEST_PROTOCOL),
  'client_request_id': matches(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),
  'agent_definition': oneOf(...CAPABILITY_TIERS),
  'capability_tier': oneOf(...CAPABILITY_TIERS),
  'pack_role_reference': (v) => isStr(v) && isContractId(v),
  'contract_draft.schema': (v) => v === CONTRACT_SCHEMA_VERSION,
  'contract_draft.task_id': (v) => isStr(v) && isContractId(v),
  'contract_draft.mode': oneOf(...MODES),
  'contract_draft.risk': oneOf(...RISKS),
  'contract_draft.pack_id': (v) => isStr(v) && isContractId(v),
  'contract_draft.agent_id': (v) => isStr(v) && isContractId(v),
  'contract_draft.scope': (v) => isStr(v) && isWorkPath(v),
  'contract_draft.prohibited_scope': (v) => isStr(v) && isWorkPath(v),
  'contract_draft.inputs': (v) => isStr(v) && isRepoPath(v),
  'contract_draft.core_skills': (v) => isStr(v) && isContractId(v),
  'contract_draft.additional_skills': (v) => isStr(v) && isContractId(v),
  'contract_draft.reference_skills': (v) => isStr(v) && isContractId(v),
  'contract_draft.verification.required': (v) => typeof v === 'boolean',
  'contract_draft.verification.verifier_agent_id': (v) => isStr(v) && isContractId(v),
};

/**
 * The leaves that are prose by design, each with the reason it must stay prose. This set is the
 * honest statement of route 1's surface: these — and only these — are places a credential could
 * ride, and no check in this process can tell one from a sentence.
 */
const DECLARED_FREE_TEXT = new Set([
  'contract_draft.title',                      // what a person calls the task
  'contract_draft.objective',                  // the instruction the agent reads
  'contract_draft.assignee_role',              // a human role name, any script
  'contract_draft.done_criteria',              // acceptance sentences
  'contract_draft.verification.verifier_role', // a human role name
  'contract_draft.verification.commands',      // shell the verifier runs
  'contract_draft.rollback.strategy',          // the note route 1 uses
  'contract_draft.rollback.commands',          // shell the rollback runs
]);

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

  it('route 2 is CLOSED: the compound `key` forms are matched, and ordinary prose is not', () => {
    for (const word of ['pubkey', 'apikey', 'api_key', 'API-KEY', 'keystore',
                        'sessionkey', 'keychain', 'keyring', 'keyfile', 'keypair', 'key_id']) {
      expect(FORBIDDEN.test(word), `${word} must be matched`).toBe(true);
    }
    // The bare word still is — the prefix and suffix groups are both optional, so nothing the old
    // pattern caught was traded away.
    expect(FORBIDDEN.test('key')).toBe(true);
    // And the reason a lookaround existed at all: a sweep that fires on ordinary words gets deleted.
    for (const word of ['monkey', 'turkey', 'donkey', 'hockey', 'whiskey',
                        'keyboard', 'keyword', 'keynote']) {
      expect(FORBIDDEN.test(word), `${word} must NOT be matched`).toBe(false);
    }
  });

  it('route 2 mutant: the pattern this replaced misses every compound form', () => {
    // Delete the widening and this is what comes back. Kept executable so a future simplification
    // that "tidies" the pattern back to a bare word boundary cannot land quietly.
    const SUPERSEDED = /lease|(?<![a-z])key(?![a-z])|secret|token|nonce|signature|private/i;
    for (const word of ['pubkey', 'apikey', 'keystore', 'sessionkey']) {
      expect(SUPERSEDED.test(word), `${word} was missed by the superseded pattern`).toBe(false);
      expect(FORBIDDEN.test(word), `${word} is caught by the current one`).toBe(true);
    }
  });

  it('route 3 is CLOSED: a character-code array is decoded and caught', async () => {
    const bytes = Array.from('lease-7f2a91').map((c) => c.charCodeAt(0));
    const sent = await wire({ ...BASE, doneCriteria: ['done'], verificationCommands: [] });
    const swept = flatten({ ...(sent as object), smuggled: bytes });
    expect(swept, 'the sweep sees the bytes as the text they decode to').toContain('lease-7f2a91');
    expect(swept.filter((s) => FORBIDDEN.test(s)).length,
      'and therefore has something to say about it').toBeGreaterThan(0);
  });

  it('route 3 mutant: the string-only sweep this replaced sees nothing', () => {
    const bytes = Array.from('lease-7f2a91').map((c) => c.charCodeAt(0));
    const superseded = (v: unknown, out: string[] = []): string[] => {
      if (typeof v === 'string') out.push(v);
      else if (Array.isArray(v)) v.forEach((x) => superseded(x, out));
      else if (v && typeof v === 'object') {
        for (const [k, x] of Object.entries(v)) { out.push(k); superseded(x, out); }
      }
      return out;
    };
    expect(superseded({ smuggled: bytes }).filter((s) => FORBIDDEN.test(s))).toEqual([]);
    expect(flatten({ smuggled: bytes }).filter((s) => FORBIDDEN.test(s)).length).toBeGreaterThan(0);
  });

  it('route 3: a non-code numeric array is left alone — the decode is not a wildcard', () => {
    // Only an array that is ENTIRELY printable ASCII decodes. A list of ordinary numbers must not
    // acquire a spurious text form, or the sweep starts inventing offenders.
    expect(flatten({ counts: [1, 2, 3, 999] })).not.toContain(String.fromCharCode(1, 2, 3));
    expect(flatten({ counts: [1, 2, 3, 999] })).toEqual(['counts', '1', '2', '3', '999']);
  });

  it('every leaf is either shape-constrained or a DECLARED free-text field', async () => {
    // The property route 1 cannot have, stated as the one that IS available: not "no credential
    // travels" (undecidable here) but "the set of places one COULD travel is enumerated". A new
    // field turns this red on the commit that adds it, which is the moment a reviewer should look.
    const sent = await wire(BASE);
    const unknown = leafPaths(sent).filter(
      ({ path, value }) => {
        const shape = SHAPE_CONSTRAINED[path];
        if (shape) return !shape(value);
        return !DECLARED_FREE_TEXT.has(path);
      },
    );
    expect(unknown, 'an undeclared or misshapen leaf reached the wire').toEqual([]);
  });

  it('the register is not vacuous: an undeclared field fails, a misshapen id fails', async () => {
    const sent = await wire(BASE) as Record<string, unknown>;
    // A field nobody declared.
    const widened = { ...sent, operator_note: 'anything at all' };
    expect(leafPaths(widened).filter(({ path, value }) => {
      const shape = SHAPE_CONSTRAINED[path];
      if (shape) return !shape(value);
      return !DECLARED_FREE_TEXT.has(path);
    }).map((l) => l.path)).toEqual(['operator_note']);
    // A declared field whose value stops matching its real validator.
    const draft = { ...(sent.contract_draft as Record<string, unknown>), task_id: 'Not An Id' };
    expect(leafPaths({ ...sent, contract_draft: draft })
      .filter(({ path, value }) => {
        const shape = SHAPE_CONSTRAINED[path];
        return shape ? !shape(value) : !DECLARED_FREE_TEXT.has(path);
      }).map((l) => l.path)).toEqual(['contract_draft.task_id']);
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
