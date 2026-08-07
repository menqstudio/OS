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

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
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
      // A missing/odd value must never be read as "verified".
      authenticated: raw.authenticated === true,
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
