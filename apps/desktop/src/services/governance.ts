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
  /** Present only for `ok`: the engine-mirrored, schema-valid records (read-only). */
  records?: unknown[];
}

/** A page is showing engine truth only when the mirror is `ok`. */
export function isMirrored(r: GovernanceRead): boolean {
  return r.state === 'ok';
}

/** `true` for any honest non-fabricated blocked state (engine refused OR unreachable). */
export function isBlockedOrUnreachable(r: GovernanceRead): boolean {
  return r.state === 'blocked' || r.state === 'unreachable';
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
    return { state: 'unreachable', surface, reason: 'engine reply was not an object' };
  }
  const state = raw.state;
  const replySurface = typeof raw.surface === 'string' ? raw.surface : surface;
  if (state === 'ok') {
    if (!Array.isArray(raw.records)) {
      // An `ok` reply with no records array is malformed — refuse to treat it as mirrored.
      return { state: 'blocked', surface: replySurface, reason: 'engine ok reply had no records array' };
    }
    return { state: 'ok', surface: replySurface, records: raw.records };
  }
  if (state === 'blocked' || state === 'unreachable') {
    const reason = typeof raw.reason === 'string' && raw.reason ? raw.reason : undefined;
    return { state, surface: replySurface, reason };
  }
  // Unknown state → fail closed as unreachable (never `ok`).
  return { state: 'unreachable', surface, reason: `unrecognized engine reply state ${String(state)}` };
}
