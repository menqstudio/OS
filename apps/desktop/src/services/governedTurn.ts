// Wave 3b-1B — renderer-side governed-turn service (the design-GREEN rev-30 §4.10(g) RENDERER half).
//
// The renderer is the untrusted, thin proxy: it sends the broker ONLY a closed
// { conversation_id, agent?, client_request_id } command and renders the broker's committed reply
// read-only. It NEVER constructs, mutates, or marks a message `trusted_verified`; the only way a message
// renders as "Verified" is a broker-emitted `committed` frame authenticated over the peer-pinned IPC.
// A forged or renderer-originated event can never be shown as Verified — this module refuses to treat any
// frame as verified unless it is a well-formed broker `committed` result with trust_state === the one
// allowed value.

export const REQUEST_PROTOCOL = 'brops.renderer-governed-turn.v1';
export const RESULT_PROTOCOL = 'brops.renderer-governed-turn-result.v1';
export const TRUSTED_VERIFIED = 'trusted_verified';

/** The CLOSED renderer-facing refusal reasons (rev-30 P0). */
export const TURN_REASONS = [
  'malformed', 'peer_denied', 'retry_conflict', 'turn_in_progress',
  'commit_readback_mismatch', 'upstream_blocked',
] as const;
export type TurnReason = (typeof TURN_REASONS)[number];

/** The exact request frame the thin proxy sends — ONLY these fields ever leave the renderer. */
export interface GovernedTurnRequest {
  protocol: typeof REQUEST_PROTOCOL;
  conversation_id: string;
  agent?: string;
  client_request_id: string;
}

/** The broker-produced immutable message projection (rev-30 P0). Read-only in the renderer. */
export interface CommittedMessage {
  messageId: string;
  role: 'assistant';
  author: string;
  body: string;
  createdAtMs: number;
  trustState: typeof TRUSTED_VERIFIED;
}

export type GovernedTurnResult =
  | { status: 'committed'; clientRequestId: string; brokerTurnId: string; conversationId: string; message: CommittedMessage }
  | { status: 'blocked'; clientRequestId: string; brokerTurnId: string; conversationId: string; reason: TurnReason };

/** A UUIDv4 generator (real: `crypto.randomUUID`; injectable for tests). */
export type IdGen = () => string;

/** The broker transport: sends the closed request frame, resolves with the raw reply. In the Tauri
 * runtime this wraps `invoke('governed_turn_execute', …)`; tests inject a fake. */
export type BrokerTransport = (request: GovernedTurnRequest) => Promise<unknown>;

const UUIDV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Build the closed request frame — ONLY conversation_id, agent?, client_request_id (P1-1 correlation). */
export function buildRequest(conversationId: string, agent: string | undefined, genId: IdGen): GovernedTurnRequest {
  const clientRequestId = genId();
  if (!UUIDV4.test(clientRequestId)) {
    throw new Error('client_request_id must be a lowercase UUIDv4');
  }
  const req: GovernedTurnRequest = {
    protocol: REQUEST_PROTOCOL,
    conversation_id: conversationId,
    client_request_id: clientRequestId,
  };
  if (agent !== undefined) req.agent = agent;
  return req;
}

function asRecord(v: unknown): Record<string, unknown> {
  if (typeof v !== 'object' || v === null) throw new Error('governed-turn reply is not an object');
  return v as Record<string, unknown>;
}
function str(o: Record<string, unknown>, k: string): string {
  const v = o[k];
  if (typeof v !== 'string') throw new Error(`governed-turn reply field '${k}' is not a string`);
  return v;
}

/**
 * Parse + validate the broker reply into a typed result. Fails (throws) on any frame that is not a
 * well-formed rev-30 result: wrong protocol, unknown status, a `committed` frame whose message is not a
 * complete assistant projection with trust_state === 'trusted_verified', or a `blocked` frame whose reason
 * is outside the closed enum. A `blocked` frame that carries a `message` is also rejected.
 */
export function parseResult(raw: unknown): GovernedTurnResult {
  const o = asRecord(raw);
  if (o.protocol !== RESULT_PROTOCOL) throw new Error('governed-turn reply: wrong protocol');
  const clientRequestId = str(o, 'client_request_id');
  const brokerTurnId = str(o, 'broker_turn_id');
  const conversationId = str(o, 'conversation_id');
  const status = o.status;
  if (status === 'committed') {
    if ('reason' in o) throw new Error('committed frame must not carry a reason');
    const m = asRecord(o.message);
    if (m.role !== 'assistant') throw new Error('committed message role must be assistant');
    if (m.trust_state !== TRUSTED_VERIFIED) throw new Error('committed message is not trusted_verified');
    const createdAtMs = o.message && typeof (m.created_at_ms) === 'number' ? (m.created_at_ms as number) : NaN;
    if (!Number.isFinite(createdAtMs)) throw new Error('committed message created_at_ms invalid');
    const message: CommittedMessage = {
      messageId: str(m, 'message_id'),
      role: 'assistant',
      author: str(m, 'author'),
      body: str(m, 'body'),
      createdAtMs,
      trustState: TRUSTED_VERIFIED,
    };
    return { status: 'committed', clientRequestId, brokerTurnId, conversationId, message };
  }
  if (status === 'blocked') {
    if ('message' in o) throw new Error('blocked frame must not carry a message');
    const reason = o.reason;
    if (typeof reason !== 'string' || !(TURN_REASONS as readonly string[]).includes(reason)) {
      throw new Error('blocked frame reason is outside the closed enum');
    }
    return { status: 'blocked', clientRequestId, brokerTurnId, conversationId, reason: reason as TurnReason };
  }
  throw new Error(`governed-turn reply: unknown status ${String(status)}`);
}

/**
 * `true` ONLY for a broker-emitted `committed` result whose message is `trusted_verified`. This is the
 * SOLE source of a "Verified" badge in the UI — the renderer has no other path to it.
 *
 * Accepts a [`GovernedTurnAttempt`] too, so a UI that holds the wider type cannot accidentally reach a
 * "Verified" affordance through the narrow one: an `unavailable` attempt is never verified.
 */
export function isVerified(result: GovernedTurnResult | GovernedTurnAttempt): boolean {
  return result.status === 'committed' && result.message.trustState === TRUSTED_VERIFIED;
}

/** Run one governed turn: build the closed request, send it through the broker transport, and parse the
 * committed/blocked reply. Never throws for a well-formed `blocked` reply (that is a normal outcome). */
export async function runGovernedTurn(
  conversationId: string,
  agent: string | undefined,
  transport: BrokerTransport,
  genId: IdGen,
): Promise<GovernedTurnResult> {
  const request = buildRequest(conversationId, agent, genId);
  const raw = await transport(request);
  return parseResult(raw);
}

// --- Non-decisions: the outcomes in which NO broker verdict exists ------------------------------
//
// `runGovernedTurn` throws for every failure that is not a well-formed broker reply, which collapses
// three very different facts into one rejected promise:
//
//   * the broker DECIDED and refused        → `{ status: 'blocked', reason }` (a verdict)
//   * the broker was never reached          → no verdict exists at all
//   * the broker answered something illegal → no verdict exists at all
//
// The Rust proxy (`src-tauri/src/governed_turn.rs`) deliberately keeps those apart with three stable,
// mutually-distinguishable machine prefixes, and its own tests assert they can never masquerade as one
// another. A renderer that shows a thrown transport error the same way it shows a broker refusal throws
// that distinction away — and, worse, tempts a UI into reading "we could not reach the broker" as
// "the broker said no". Everything below preserves the distinction all the way to the screen.

/**
 * Why a governed turn produced NO broker verdict. Every member means the same thing about trust: the
 * broker neither allowed nor refused this turn, so nothing here may ever be rendered as a decision.
 *
 * The first five mirror the proxy's stable prefixes verbatim; the last two are renderer-side facts.
 */
export const NON_DECISIONS = [
  /** No governed-broker IPC transport is compiled for this host — a platform fact, not a failure. */
  'broker_unsupported_platform',
  /** A transport exists for this host, but the connection to the broker could not be established. */
  'broker_unavailable',
  /** Connected to the broker, but the framed exchange failed. Still not a broker verdict. */
  'broker_transport_failed',
  /** The proxy could not serialize the request frame. It never left the desktop. */
  'malformed_request',
  /** Something answered, but its reply is not a well-formed rev-30 result frame. */
  'malformed_broker_reply',
  /** There is no Tauri backend at all (a plain browser) — the proxy command does not exist here. */
  'no_desktop_backend',
  /** The transport rejected with something outside the taxonomy above. Reported verbatim, never
   *  silently folded into one of the named cases. */
  'unclassified_transport_failure',
] as const;
export type NonDecision = (typeof NON_DECISIONS)[number];

/** A governed turn that produced no verdict. Deliberately NOT `status: 'blocked'`. */
export interface GovernedTurnUnavailable {
  status: 'unavailable';
  kind: NonDecision;
  /** The verbatim machine reason, for display and for logs. Never interpreted as a verdict. */
  detail: string;
}

/** Every honest outcome of attempting a governed turn: a broker DECISION, or a non-decision. */
export type GovernedTurnAttempt = GovernedTurnResult | GovernedTurnUnavailable;

/** `true` only when the broker itself decided this turn (committed OR blocked). */
export function isBrokerDecision(a: GovernedTurnAttempt): a is GovernedTurnResult {
  return a.status === 'committed' || a.status === 'blocked';
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Map a rejected `governed_turn_execute` invoke onto the non-decision taxonomy by its stable machine
 * prefix. An unrecognised rejection becomes `unclassified_transport_failure` — never a named case it
 * did not actually report, and never a broker verdict.
 */
export function classifyTransportFailure(e: unknown): { kind: NonDecision; detail: string } {
  const detail = messageOf(e);
  for (const kind of ['broker_unsupported_platform', 'broker_unavailable', 'broker_transport_failed'] as const) {
    if (detail.startsWith(kind)) return { kind, detail };
  }
  if (detail === 'malformed_request') return { kind: 'malformed_request', detail };
  if (detail === 'malformed_broker_reply') return { kind: 'malformed_broker_reply', detail };
  return { kind: 'unclassified_transport_failure', detail };
}

/**
 * Attempt one governed turn and return an outcome instead of throwing.
 *
 * This never invents a verdict. A `committed`/`blocked` result is returned ONLY when the broker really
 * produced a well-formed rev-30 frame; every other path — a request that could not even be built, a
 * transport that rejected, a reply that failed validation — returns `unavailable` with the honest
 * machine reason. `isVerified` stays the single gate for a "Verified" affordance, and it is false for
 * every `unavailable` outcome by construction.
 */
export async function attemptGovernedTurn(
  conversationId: string,
  agent: string | undefined,
  transport: BrokerTransport,
  genId: IdGen,
): Promise<GovernedTurnAttempt> {
  let request: GovernedTurnRequest;
  try {
    request = buildRequest(conversationId, agent, genId);
  } catch (e) {
    // The frame never left the renderer, so nothing was asked of the broker.
    return { status: 'unavailable', kind: 'malformed_request', detail: messageOf(e) };
  }
  let raw: unknown;
  try {
    raw = await transport(request);
  } catch (e) {
    return { status: 'unavailable', ...classifyTransportFailure(e) };
  }
  try {
    // A well-formed `blocked` frame parses fine — that IS a broker decision and stays one.
    return parseResult(raw);
  } catch (e) {
    // Something answered but the answer is not a legal result frame. Refusing to interpret it is the
    // whole point: an illegal frame must never be upgraded into a verdict of either sign.
    return { status: 'unavailable', kind: 'malformed_broker_reply', detail: messageOf(e) };
  }
}
