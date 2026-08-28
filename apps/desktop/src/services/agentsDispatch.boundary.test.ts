import { describe, it, expect } from 'vitest';
import {
  buildAssignment, attemptDispatch, validateAssignment, isContractId, isRepoPath, isWorkPath,
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
 * Routes 2 and 3 were closed in the eighth round's remediation and the NINTH audit re-ran both
 * mutants independently and could not reopen either. It reopened `A-09` for a third reason, and
 * that reason was this file's own sentence about route 1.
 *
 * # The register said eight, and the register was wrong — ninth audit `I-01`, `I-02`, `I-03`
 *
 * The previous revision answered route 1 by declaring an eight-leaf free-text register and writing
 * *"these — and only these — are places a credential could ride."* Three things were wrong with it,
 * and all three are fixed here:
 *
 *   * **`I-01` — "shape-constrained" was doing work a shape cannot do.** Eleven further leaves are
 *     bound by `isContractId`, `isRepoPath` or `isWorkPath`, and every one of those patterns admits
 *     a credential: `^[a-z0-9][a-z0-9._-]{1,127}$` takes a 64-character hex secret whole, and
 *     `slug()` lowercases caller input on the way in, so it arrives verbatim. A shape is not a
 *     capacity. The register is COMPUTED now rather than asserted: {@link CREDENTIAL_PROBES} is run
 *     through each leaf's REAL validator, and a leaf whose validator admits a probe must be declared
 *     a carrier. Loosen a validator and the declaration stops matching what the code admits.
 *   * **`I-02` — three of the eight declared entries were never exercised, and deleting them was
 *     green.** `BASE` leaves `verifierRole`/`verifierAgentSlug` null and both command arrays empty,
 *     and `leafPaths` drops nulls and empty arrays, so those leaves never reached the assertion —
 *     which only ever checked that a *present* leaf is declared, never that a *declared* leaf is
 *     real. Four shape-constrained entries (`inputs`, `additional_skills`, `reference_skills`,
 *     `verification.verifier_agent_id`) were unexercised for exactly the same reason, so the true
 *     count was seven, not three. {@link FULL} populates every optional field and
 *     `the register has no unreachable entries` asserts the inverse direction.
 *   * **`I-03` — one byte outside `0x20`–`0x7e` walked past the decode.** `decodeCharCodes` returned
 *     `null` for the whole array if any element was out of range, so appending `0x0a` to the
 *     character-code array defeated it entirely. It decodes printable RUNS now, and additionally the
 *     printable bytes with the separators removed, so interleaving does not hide the text either.
 *
 * # Route 1 is still not closed, and is still not claimed to be
 *
 * A credential is defined by what a remote system will accept, not by anything about its text: an
 * opaque token and a rollback note are the same bytes to this process. The candidate fix — a
 * high-entropy detector — is a heuristic that would fire on legitimate ids, digests and hashes, and
 * a heuristic that reads as proof is worse than the honest gap, because the next roadmap row would
 * cite it too. A declared *grammar* for the free-text fields fails the same way from the other side:
 * tight enough to exclude a JWT also excludes a commit sha, a path, a URL and an Armenian sentence;
 * loose enough for prose admits a token by adding a space.
 *
 * **What IS established, and it is not a heuristic:** the set of leaves that can carry a credential
 * is enumerated, and the enumeration is derived from the validators the product actually runs. A new
 * field, or a widened validator, turns this file red on the commit that does it.
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

/**
 * The same assignment with **every optional field populated** — ninth audit `I-02`.
 *
 * `BASE` alone leaves seven register entries unreachable, and an entry that is never reached is an
 * entry that can be deleted without a test noticing. Nothing here is exotic: it is the shape a real
 * dispatch takes when a verifier is named and a rollback is scripted.
 */
const FULL: AssignmentInput = {
  ...BASE,
  // `builder`, not `reader`: `validateAssignment` refuses rollback commands to a tier that cannot
  // change files, and a refused assignment never reaches the wire — which is how a fixture stops
  // exercising anything without saying so. `both fixtures really do dispatch` pins that.
  tier: 'builder',
  inputs: ['docs/ARCHITECTURE.md'],
  additionalSkills: ['analysis-secondary'],
  referenceSkills: ['reference-reading'],
  verifierAgentSlug: 'ledger-verifier',
  verifierRole: 'Ledger Verifier',
  verificationCommands: ['npm run test -- ledger'],
  rollbackCommands: ['git checkout -- .'],
};

const UUID = 'ffffffff-ffff-4fff-8fff-ffffffffffff';

/**
 * Every string that appears anywhere in a value, however deeply nested.
 *
 * **Non-string leaves are visited too** (sixth audit `A-09` route 3, reopened by the eighth).
 * The earlier version pushed only `typeof value === 'string'`, so a `number[]` whose elements
 * are character codes decoded to `"lease-7f2a91"` on the far side while being invisible here.
 * Numbers and booleans are now stringified, and an array's printable character codes are
 * additionally pushed in decoded form — the sweep sees the bytes as the text they would become,
 * not as digits.
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
 * `0x20`–`0x7e`, so a newline on the end of the character-code array made it invisible again. Two
 * things are produced instead, and the second is the one that matters: every maximal printable RUN,
 * so adjacency is preserved, **and** the concatenation of all printable bytes with the
 * non-printable ones removed, so a credential interleaved with separators cannot hide either. An
 * array with no printable byte in it yields nothing at all, which is what keeps the decode from
 * becoming a wildcard that invents offenders.
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
 *
 * Being in this map means the value's SHAPE is pinned. It does **not** mean its capacity is
 * bounded; {@link CREDENTIAL_CAPABLE} is the set that says which of these can still carry a secret.
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
 * The leaves that are prose by design, each with the reason it must stay prose.
 *
 * This is no longer claimed to be the whole of route 1's surface — {@link CREDENTIAL_CAPABLE} is
 * the set that claim belongs to. It is the subset that has no validator at all.
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

/**
 * Credential-shaped strings, in the forms a real secret arrives in — ninth audit `I-01`.
 *
 * Two of them are lowercase-and-alphanumeric on purpose: `slug()` lowercases and strips, so those
 * are the shapes that survive the id path verbatim. If a probe ever stopped being credential-shaped
 * the capacity check would weaken silently, so `the probes are really credential-shaped` pins them.
 */
const CREDENTIAL_PROBES: ReadonlyArray<readonly [name: string, value: string]> = [
  ['64-hex secret', '7f2a91c4e08b45d9a1f36c27be5049d83a7e1b6045cf92d8e3ab7710c65d4f92'],
  ['base64url token body', 'dqx1_ab2cd3ef4gh5ij6kl7mn8op9qr0st1uv2wx3yz4a5b6'],
  ['signed JWT', 'eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiI3ZjJhOTEifQ.3xR9'],
  ['dotted opaque id', 'v1.7f2a91c4e08b45d9a1f36c27be5049d8'],
];

/**
 * Every leaf a caller's input reaches. `protocol`, `contract_draft.schema`, `client_request_id` and
 * `verification.required` are excluded because the module produces them: two constants, a generated
 * UUID and a boolean derived from `risk`. The UUID has 122 bits of capacity and could in principle
 * carry a secret, but nothing the caller passes decides it, so it is not a route.
 */
const CALLER_CONTROLLED = new Set([
  'agent_definition', 'capability_tier', 'pack_role_reference',
  'contract_draft.task_id', 'contract_draft.mode', 'contract_draft.risk',
  'contract_draft.pack_id', 'contract_draft.agent_id',
  'contract_draft.scope', 'contract_draft.prohibited_scope', 'contract_draft.inputs',
  'contract_draft.core_skills', 'contract_draft.additional_skills',
  'contract_draft.reference_skills',
  'contract_draft.verification.verifier_agent_id',
  ...DECLARED_FREE_TEXT,
]);

/**
 * The honest answer to *"where could a credential ride?"* — nineteen leaves, not eight.
 *
 * Eight have no validator. Eleven have one that admits a credential anyway: eight bound by
 * `isContractId` (128 characters of `[a-z0-9._-]`, which a 64-hex secret fits inside twice over)
 * and three by the path validators, which take a JWT whole because a JWT contains no slash, space
 * or reserved character. This list is ASSERTED equal to the list COMPUTED from the validators, so
 * it cannot drift from what the code admits.
 */
const CREDENTIAL_CAPABLE = new Set([
  ...DECLARED_FREE_TEXT,
  'pack_role_reference',
  'contract_draft.task_id',
  'contract_draft.pack_id',
  'contract_draft.agent_id',
  'contract_draft.core_skills',
  'contract_draft.additional_skills',
  'contract_draft.reference_skills',
  'contract_draft.verification.verifier_agent_id',
  'contract_draft.scope',
  'contract_draft.prohibited_scope',
  'contract_draft.inputs',
]);

/** The leaves whose validator lets at least one {@link CREDENTIAL_PROBES} value through. */
function credentialCapable(shapes: Record<string, (v: unknown) => boolean>): Set<string> {
  const out = new Set<string>();
  for (const path of CALLER_CONTROLLED) {
    const shape = shapes[path];
    if (!shape) { out.add(path); continue; }                 // no validator at all
    if (CREDENTIAL_PROBES.some(([, v]) => shape(v))) out.add(path);
  }
  return out;
}

const undeclared = (frame: unknown) => leafPaths(frame).filter(({ path, value }) => {
  const shape = SHAPE_CONSTRAINED[path];
  return shape ? !shape(value) : !DECLARED_FREE_TEXT.has(path);
});

async function wire(input: AssignmentInput): Promise<unknown> {
  let sent: unknown = null;
  await attemptDispatch(buildAssignment(input), async (req) => { sent = req; return null; }, () => UUID);
  return sent;
}

describe('the no-lease sweep proves the FRAME, not the absence of a credential', () => {
  it('both fixtures really do dispatch — a refused one exercises nothing', () => {
    // The failure mode `I-02` was made of: a fixture that does not reach the wire cannot make any
    // register entry reachable, and nothing said so. `validateAssignment` is the module's own
    // refusal, so an invalid fixture is a red test rather than a silently smaller register.
    for (const [name, input] of [['BASE', BASE], ['FULL', FULL]] as const) {
      expect(validateAssignment(buildAssignment(input)), `${name} must be locally well-formed`)
        .toEqual([]);
    }
  });

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
    // Only printable bytes decode. A list of ordinary numbers must not acquire a spurious text
    // form, or the sweep starts inventing offenders.
    expect(flatten({ counts: [1, 2, 3, 999] })).not.toContain(String.fromCharCode(1, 2, 3));
    expect(flatten({ counts: [1, 2, 3, 999] })).toEqual(['counts', '1', '2', '3', '999']);
  });

  it('`I-03`: one out-of-range byte no longer walks past the decode', () => {
    // The ninth audit's escape, executable. A single 0x0a on the end defeated the all-or-nothing
    // form completely; interleaving one between every character defeated it even more cheaply.
    const trailing = [...Array.from('lease-7f2a91').map((c) => c.charCodeAt(0)), 0x0a];
    const interleaved = Array.from('lease-7f2a91').flatMap((c) => [c.charCodeAt(0), 0x0a]);
    for (const bytes of [trailing, interleaved]) {
      expect(flatten({ smuggled: bytes }), 'the printable bytes decode with the separators removed')
        .toContain('lease-7f2a91');
      expect(flatten({ smuggled: bytes }).filter((s) => FORBIDDEN.test(s)).length)
        .toBeGreaterThan(0);
    }
  });

  it('`I-03` mutant: the all-or-nothing decode this replaced sees nothing', () => {
    const superseded = (list: readonly unknown[]): string | null => {
      if (list.length === 0) return null;
      const codes: number[] = [];
      for (const v of list) {
        if (typeof v !== 'number' || !Number.isInteger(v) || v < 0x20 || v > 0x7e) return null;
        codes.push(v);
      }
      return String.fromCharCode(...codes);
    };
    const trailing = [...Array.from('lease-7f2a91').map((c) => c.charCodeAt(0)), 0x0a];
    expect(superseded(trailing), 'the superseded decode gave up on the whole array').toBeNull();
    expect(decodeCharCodeRuns(trailing)).toContain('lease-7f2a91');
    // And the property that keeps the replacement from being a wildcard is preserved.
    expect(decodeCharCodeRuns([1, 2, 3, 999])).toEqual([]);
  });

  it('every leaf is either shape-constrained or a DECLARED free-text field', async () => {
    // Both fixtures, because BASE alone never populates seven of the register's entries.
    for (const input of [BASE, FULL]) {
      expect(undeclared(await wire(input)),
        'an undeclared or misshapen leaf reached the wire').toEqual([]);
    }
  });

  it('the register has no unreachable entries — `I-02`', async () => {
    // The inverse direction, which is the one that was missing: an entry no fixture reaches is an
    // entry that can be deleted without a test noticing, and three free-text plus four
    // shape-constrained entries were in exactly that state.
    const reached = new Set<string>();
    for (const input of [BASE, FULL]) {
      for (const { path } of leafPaths(await wire(input))) reached.add(path);
    }
    const declared = [...Object.keys(SHAPE_CONSTRAINED), ...DECLARED_FREE_TEXT];
    expect(declared.filter((p) => !reached.has(p)),
      'a declared entry that no fixture populates is not being tested').toEqual([]);
  });

  it('`I-02` mutant: deleting a declared entry is no longer green', async () => {
    // Precisely the audit's attack. `contract_draft.rollback.commands` was one of the three that
    // could be deleted with all ten tests still passing; with FULL populating it, its absence from
    // the register is a failure the suite reports.
    const shrunk = new Set(DECLARED_FREE_TEXT);
    shrunk.delete('contract_draft.rollback.commands');
    const missed = leafPaths(await wire(FULL)).filter(({ path, value }) => {
      const shape = SHAPE_CONSTRAINED[path];
      return shape ? !shape(value) : !shrunk.has(path);
    }).map((l) => l.path);
    expect(missed).toEqual(['contract_draft.rollback.commands']);
  });

  it('the probes are really credential-shaped', () => {
    // The capacity check is only as honest as its probes. A probe that stopped looking like a
    // secret would quietly shrink the computed set, so the shapes are pinned here.
    const [hex, b64, jwt, dotted] = CREDENTIAL_PROBES.map(([, v]) => v);
    expect(hex).toMatch(/^[0-9a-f]{64}$/);
    expect(b64.length).toBeGreaterThanOrEqual(43);
    expect(jwt.split('.')).toHaveLength(3);
    expect(dotted).toMatch(/^v1\.[0-9a-f]{32}$/);
    // And none of them says anything the FORBIDDEN sweep could catch — that is the whole point.
    for (const [, v] of CREDENTIAL_PROBES) expect(FORBIDDEN.test(v)).toBe(false);
  });

  it('`I-01`: the credential-capable set is COMPUTED from the real validators, and it is 19', () => {
    // The sentence this replaces said eight. Eleven more leaves are bound by patterns that admit a
    // secret whole: `isContractId` takes 128 characters of [a-z0-9._-], and the path validators
    // take a JWT because a JWT has no slash, space or reserved character in it.
    expect([...credentialCapable(SHAPE_CONSTRAINED)].sort()).toEqual([...CREDENTIAL_CAPABLE].sort());
    expect(CREDENTIAL_CAPABLE.size).toBe(19);
    expect(DECLARED_FREE_TEXT.size).toBe(8);
  });

  it('`I-01`: a 64-hex secret really does reach the wire through a shape-constrained leaf', async () => {
    // Measured, not argued. `slug()` lowercases and strips, and a lowercase hex string has nothing
    // to strip, so the value arrives verbatim in a field the register used to call constrained.
    //
    // The probe comes from CREDENTIAL_PROBES rather than being written out again here. Restating
    // the literal made a second copy that reads exactly like a credential assignment -- `gitleaks`
    // flagged this line as `generic-api-key` and it was right to: a synthetic value and a real one
    // are the same bytes to a scanner, which is this file's whole subject one level up. One
    // definition, used by both the capacity check and the demonstration.
    const [, probe] = CREDENTIAL_PROBES[0];
    const sent = await wire({ ...BASE, taskId: probe });
    expect(flatten(sent), 'the probe is on the wire').toContain(probe);
    expect(undeclared(sent), 'and every leaf still validates — the shape check is blind to it')
      .toEqual([]);
    expect(flatten(sent).filter((s) => FORBIDDEN.test(s)), 'and the sweep is silent').toEqual([]);
  });

  it('`I-01` mutant: tightening a validator moves the computed set, and the declaration notices', () => {
    // The check earns its place only if the two sides can disagree. Bind `task_id` to a shape a
    // credential cannot fit and the computed set loses it — which is a failure until someone
    // updates the declaration deliberately.
    const tightened = { ...SHAPE_CONSTRAINED, 'contract_draft.task_id': matches(/^task-\d+$/) };
    const computed = credentialCapable(tightened);
    expect(computed.has('contract_draft.task_id')).toBe(false);
    expect(computed.size).toBe(CREDENTIAL_CAPABLE.size - 1);
  });

  it('the register is not vacuous: an undeclared field fails, a misshapen id fails', async () => {
    const sent = await wire(BASE) as Record<string, unknown>;
    // A field nobody declared.
    expect(undeclared({ ...sent, operator_note: 'anything at all' }).map((l) => l.path))
      .toEqual(['operator_note']);
    // A declared field whose value stops matching its real validator.
    const draft = { ...(sent.contract_draft as Record<string, unknown>), task_id: 'Not An Id' };
    expect(undeclared({ ...sent, contract_draft: draft }).map((l) => l.path))
      .toEqual(['contract_draft.task_id']);
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
