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
 */
export function isVerified(result: GovernedTurnResult): boolean {
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
