/**
 * The renderer's view of an approval REQUEST — parsed, never trusted.
 *
 * `T-021c`. The document that crosses is `contracts/approval-request.schema.json`; the Rust side
 * (`brops_core::approval_request`) decides what may be sent and what a reply may be believed to say,
 * and this file re-checks the part a person reads. That is not redundancy for its own sake: the same
 * argument `parseGovernanceRead` was written under applies here. A renderer that trusted the IPC
 * boundary would render whatever came across it, and the one field that must never be lost on the way
 * to a pixel is `adjudicated: false`.
 *
 * WHAT THIS IS NOT. It is not the desktop's own approval system. `T-010`/`T-011` grant and deny over
 * local SQLite behind a native confirmation the webview cannot forge; that authority is real, it is
 * this app's, and it is a DIFFERENT thing with a different name. This asks the ENGINE to record a
 * request, which only an owner-signed control-room command can then adjudicate. Keeping the two
 * separately named in the UI is one of the five invariants `docs/OWNER_ACTION_REQUIRED.md` fixed
 * before this path was built.
 */

/** The three asks the contract allows, in the signed command's own vocabulary. */
export const REQUESTABLE_COMMANDS = ['approve', 'deny', 'request-verification'] as const;
export type RequestableCommand = (typeof REQUESTABLE_COMMANDS)[number];

export interface ApprovalRequestInput {
  taskId: string;
  requestedCommand: RequestableCommand;
  expectedTaskState: string;
  reason: string;
  requestedBy: string;
  evidenceRefs?: string[];
}

export type ApprovalRequestOutcome =
  | {
      state: 'recorded';
      requestId: string;
      sequence: number;
      entrySha256: string;
      duplicate: boolean;
      /** Always false. Present because losing it is the failure this type exists to prevent. */
      adjudicated: false;
      note: string;
    }
  | { state: 'refused'; reason: string }
  | { state: 'blocked'; reason: string };

const HEX64 = /^[0-9a-f]{64}$/;

function blocked(reason: string): ApprovalRequestOutcome {
  return { state: 'blocked', reason };
}

/**
 * Parse one outcome coming back over the IPC boundary.
 *
 * Fail-closed in the same three-valued way the mirror reads are: `recorded` only for a reply that says
 * so completely, `refused` for the engine's own no, and `blocked` for everything else — including a
 * reply that claims a decision, which is the shape this side must never render.
 */
export function parseApprovalRequestOutcome(raw: unknown): ApprovalRequestOutcome {
  if (typeof raw !== 'object' || raw === null) return blocked('the backend returned no outcome object');
  const doc = raw as Record<string, unknown>;

  // A decision word anywhere in the outcome is refused before `state` is even read. Only the holder of
  // a control-room key may decide an approval, and this path has none.
  for (const key of Object.keys(doc)) {
    const lower = key.toLowerCase();
    for (const word of ['granted', 'disposition', 'verdict', 'decision', 'outcome', 'approved']) {
      if (lower.includes(word)) {
        return blocked(
          `the outcome carries a \`${word}\`-shaped field; an approval is adjudicated by an ` +
            'owner-signed control-room command, never by this path',
        );
      }
    }
  }

  const state = doc.state;
  if (state === 'refused' || state === 'blocked') {
    const reason = typeof doc.reason === 'string' && doc.reason.trim() ? doc.reason : 'no reason given';
    return { state, reason };
  }
  if (state !== 'recorded') return blocked(`unknown outcome state: ${JSON.stringify(state)}`);

  if (doc.adjudicated !== false) {
    return blocked('a recorded ask that does not say `adjudicated: false` is not one this side shows');
  }
  const sequence = typeof doc.sequence === 'number' && Number.isInteger(doc.sequence) ? doc.sequence : 0;
  if (sequence < 1) return blocked('the outcome carries no usable `sequence`');
  const digest = typeof doc.entry_sha256 === 'string' ? doc.entry_sha256 : '';
  if (!HEX64.test(digest)) return blocked('the outcome carries no 64-hex `entry_sha256`');

  return {
    state: 'recorded',
    requestId: typeof doc.request_id === 'string' ? doc.request_id : '',
    sequence,
    entrySha256: digest,
    duplicate: doc.duplicate === true,
    adjudicated: false,
    note: typeof doc.note === 'string' ? doc.note : '',
  };
}
