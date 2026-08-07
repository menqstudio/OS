// Phase-2 (Governance Sidecar) — renderer-side READ-ONLY governance mirror.
//
// "Mirror, never decide." This module is the untrusted read half: it invokes the
// desktop's READ-ONLY governance IPC commands (which ask the engine sidecar) and
// parses their typed reply. It NEVER decides, approves, reweighs, or fabricates a
// verdict; the only thing it can render is what the engine mirrored — or, far more
// often in Phase-2, an honest `blocked`/`unreachable` state, because the engine read
// endpoints do not answer yet. A thrown transport error is caught and mapped to
// `unreachable` so a page always receives a typed state and never an unhandled reject.

/** The four engine governance surfaces the desktop can READ (never write). */
export type GovernanceSurface =
  | 'decisionLedger'
  | 'evidenceChain'
  | 'verdicts'
  | 'approvalQueue';

/** The honest, fail-closed states of a governance mirror read. `ok` is the ONLY
 *  state that carries engine records, and it is produced solely from a well-formed,
 *  schema-valid engine reply — never synthesized in the renderer. */
export type GovernanceReadState = 'ok' | 'blocked' | 'unreachable';

/**
 * What the ENGINE said about its own store, relayed beside the records.
 *
 * Every field is the engine SPEAKING ABOUT ITSELF. The renderer did not open the
 * engine's state directory, count anything, or verify a signature, so a page may only
 * ATTRIBUTE these — quote them as the engine's account, never restate them in the
 * app's own voice as though the desktop had established them.
 *
 * It exists because a three-valued read collapses to a blank page once the reason is
 * dropped: the engine distinguishes "the orchestration runtime holds no tasks" from
 * "the orchestration runtime has no task 't-7'" from "no task is waiting on an owner
 * approval", and without the sentence the owner cannot tell "there is nothing to show"
 * from "there is nothing to show BECAUSE ...".
 *
 * Note what is NOT here: the engine's `record_authentication` ("ed25519-signature-
 * verified"). That is the engine vouching for its own store, not a check the desktop
 * performed, so the Rust mirror drops it and `authenticated` stays `false`. Nothing on
 * this page may light up a verified affordance from the engine's say-so.
 */
export interface EngineAccount {
  /** The engine's own sentence for WHY this surface is empty. Present only when the
   *  mirrored record set really is empty, so it can never appear beside records. */
  emptyReason?: string;
  /** The engine's own count of the records it read. The number a page DISPLAYS is
   *  always `recordCount(read)` — the length of the list that arrived. */
  recordCount?: number;
  /** Only for a read filtered to one task: whether the engine's orchestration runtime
   *  has ever heard of that id. `false` means "the engine does not know this task",
   *  which is a different fact from "this task recorded nothing". */
  knownTask?: boolean;
  /** The engine's name for the store it read (`source.kind`). */
  sourceKind?: string;
}

export interface GovernanceRead {
  state: GovernanceReadState;
  surface: string;
  /** Present for `blocked`/`unreachable`: the honest machine reason. */
  reason?: string;
  /** Present only for `ok`: the engine-mirrored, schema-valid records (read-only).
   *  MAY be an empty array — an `ok` read with zero records means the sidecar had
   *  nothing to mirror. That is an EMPTY chain, never a satisfied one. */
  records?: unknown[];
  /**
   * Whether the records' ORIGIN was cryptographically verified. `false` in this build
   * and defaulted to `false` whenever the backend does not explicitly say otherwise.
   *
   * Schema validation (which the Rust mirror does) checks shape, not authorship: the
   * engine schemas declare `additionalProperties: false` and define no signature
   * field, so a conforming record cannot even carry one, and the reply comes from
   * whatever process `BROPS_GOVERNED_SIDECAR` names. So `state: 'ok'` means
   * "well-formed records arrived", not "these are genuine engine truth". A page that
   * paints a GREEN/verified affordance from this data without saying it is
   * unauthenticated is claiming more than the backend can prove.
   */
  authenticated: boolean;
  /**
   * Present only for `ok`: what the ENGINE said about its own store (see
   * [EngineAccount]). Absent for `blocked`/`unreachable`, where `reason` already
   * carries the engine's refusal or the transport's failure — "I could not look" is
   * not "I looked and found nothing", and the two must not share a field.
   */
  engine?: EngineAccount;
}

/** A page is showing engine truth only when the mirror is `ok`. */
export function isMirrored(r: GovernanceRead): boolean {
  return r.state === 'ok';
}

/** `true` for any honest non-fabricated blocked state (engine refused OR unreachable). */
export function isBlockedOrUnreachable(r: GovernanceRead): boolean {
  return r.state === 'blocked' || r.state === 'unreachable';
}

/** How many records the mirror actually carries (0 for any non-`ok` state). */
export function recordCount(r: GovernanceRead): number {
  return r.state === 'ok' ? (r.records?.length ?? 0) : 0;
}

/** `true` only when the mirror really carries records. An `ok` read with an empty
 *  record set is NOT evidence — it is the honest absence of evidence, and pages must
 *  render it as "no evidence" rather than as a satisfied node. */
export function hasRecords(r: GovernanceRead): boolean {
  return recordCount(r) > 0;
}

/** `true` when the page is showing records whose origin was NOT verified — the state
 *  every `ok` mirror is in today. Pages must say so next to anything that reads as a
 *  verdict. */
export function isUnauthenticatedMirror(r: GovernanceRead): boolean {
  return r.state === 'ok' && r.authenticated !== true;
}

/**
 * The engine's own explanation for an EMPTY surface, or `null`.
 *
 * Deliberately narrow: it answers only for an `ok` read that carried zero records.
 * A `blocked`/`unreachable` read has `reason` (the engine refused / the transport
 * failed) and an `ok` read WITH records has nothing to explain — so the three values
 * stay distinct and a page cannot accidentally print "there is nothing here because
 * ..." over a list of records or over a refusal.
 */
export function engineEmptyReason(r: GovernanceRead): string | null {
  if (r.state !== 'ok' || recordCount(r) > 0) return null;
  return r.engine?.emptyReason ?? null;
}

/** `true` when the read was filtered to a task the ENGINE says it has never heard of —
 *  the engine's claim, and a different fact from "this task recorded nothing". */
export function engineDoesNotKnowTask(r: GovernanceRead): boolean {
  return r.state === 'ok' && r.engine?.knownTask === false;
}

/** The engine's name for the store it read, or `null`. Provenance, never proof. */
export function engineSourceKind(r: GovernanceRead): string | null {
  return r.state === 'ok' ? (r.engine?.sourceKind ?? null) : null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

/**
 * Parse the engine's account, fail-QUIET per field: a missing or wrongly-typed value
 * is simply absent (there is no explanation to attribute) and is never invented. No
 * field here can promote a read to `ok`, add records, or raise its trust — the account
 * is descriptive, so a hostile value costs at most a missing sentence.
 */
function parseEngineAccount(raw: unknown): EngineAccount | undefined {
  if (!isRecord(raw)) return undefined;
  const account: EngineAccount = {};
  if (typeof raw.emptyReason === 'string' && raw.emptyReason) account.emptyReason = raw.emptyReason;
  if (typeof raw.recordCount === 'number' && Number.isFinite(raw.recordCount)) {
    account.recordCount = raw.recordCount;
  }
  if (typeof raw.knownTask === 'boolean') account.knownTask = raw.knownTask;
  if (typeof raw.sourceKind === 'string' && raw.sourceKind) account.sourceKind = raw.sourceKind;
  return Object.keys(account).length > 0 ? account : undefined;
}

/**
 * Parse the raw Rust `GovernanceRead` reply into the typed shape, FAIL-CLOSED: unless
 * the reply is a well-formed `{ state: 'ok', records: [...] }`, it degrades to `blocked`
 * (a malformed/refused reply) or `unreachable` — it will NEVER upgrade an unknown or
 * malformed reply into `ok`, so no fabricated data can ever reach a page as mirrored.
 */
export function parseGovernanceRead(surface: GovernanceSurface, raw: unknown): GovernanceRead {
  if (!isRecord(raw)) {
    return { state: 'unreachable', surface, reason: 'engine reply was not an object', authenticated: false };
  }
  const state = raw.state;
  const replySurface = typeof raw.surface === 'string' ? raw.surface : surface;
  if (state === 'ok') {
    if (!Array.isArray(raw.records)) {
      // An `ok` reply with no records array is malformed — refuse to treat it as mirrored.
      return { state: 'blocked', surface: replySurface, reason: 'engine ok reply had no records array', authenticated: false };
    }
    return {
      state: 'ok',
      surface: replySurface,
      records: raw.records,
      // Fail-closed: only a literal `true` from the backend counts as authenticated.
      // A missing/odd value must never be read as "verified". In particular this is
      // NOT derived from anything the engine says about its own store.
      authenticated: raw.authenticated === true,
      engine: parseEngineAccount(raw.engine),
    };
  }
  if (state === 'blocked' || state === 'unreachable') {
    const reason = typeof raw.reason === 'string' && raw.reason ? raw.reason : undefined;
    return { state, surface: replySurface, reason, authenticated: false };
  }
  // Unknown state → fail closed as unreachable (never `ok`).
  return {
    state: 'unreachable',
    surface,
    reason: `unrecognized engine reply state ${String(state)}`,
    authenticated: false,
  };
}
