// Where the chat's delegation surface gets its records — and, today, why it gets none.
//
// This module does not simulate a feed. It asks the backend for one and reports exactly what
// came back, including "there is no such command". That is the honest state right now: no
// Tauri command emits delegations (see `delegation.ts` for where they are dropped in
// `ai.rs::claude_cli_stream`), so `loadDelegations` resolves to `unavailable` carrying the
// backend's own words, and the surface prints them instead of drawing a card.
//
// The day `list_delegations` exists, this file needs no change — the probe succeeds and the
// same fail-closed reader parses the reply.
//
// PLACEMENT NOTE (for the backend slice): `services/desktop.ts` is "the single typed boundary
// between React and the Tauri backend", and this `invoke` belongs there beside `streamReply`.
// It sits here only because `services/` was outside this task's edit scope. When the backend
// command lands, move `probeDelegations` into `desktop.ts` and have this module call it.

import { invoke } from '@tauri-apps/api/core';
import { hasBackend } from '../services/desktop';
import { parseDelegationList, type Delegation } from './delegation';

/** Proposed name for the read-side command. See the report for the full contract. */
export const DELEGATION_LIST_COMMAND = 'list_delegations';

export type DelegationUnavailable =
  /** Not running inside Tauri (a browser, or a test) — there is no backend to ask. */
  | 'no_backend'
  /** The backend answered, and its answer is that this command does not exist. */
  | 'not_emitted'
  /** The command exists but the window capability set refuses it. */
  | 'denied'
  /** Anything else: a transport failure, or a reply this reader would not accept. */
  | 'error';

export type DelegationFeed =
  | { state: 'loading' }
  | { state: 'ready'; delegations: Delegation[] }
  | { state: 'unavailable'; reason: DelegationUnavailable; detail: string };

/** The `invoke` shape this module needs; injectable so tests drive it without a Tauri runtime. */
export type InvokeFn = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;

/**
 * Classify a rejected invoke WITHOUT softening it.
 *
 * Only a message that says the command is absent becomes `not_emitted`; only one that says it
 * was refused becomes `denied`. Everything else stays `error`, because guessing at a failure
 * is how a real broken backend ends up reading as "not built yet" and stops being fixed. The
 * detail string is always the backend's verbatim text, and every branch renders it.
 */
export function classifyDelegationFailure(message: string): DelegationUnavailable {
  const m = message.toLowerCase();
  if (/\bnot found\b/.test(m) || /unknown command/.test(m) || /no such command/.test(m)) {
    return 'not_emitted';
  }
  if (/not allowed|forbidden|denied|unauthorized|capability/.test(m)) return 'denied';
  return 'error';
}

/**
 * Ask the backend for this conversation's delegations.
 *
 * `conversationId` is optional because the chat cannot supply one yet: `Conversations.tsx`
 * keeps its selected conversation in local state and exposes no way to read it, and that file
 * is not editable here. The backend contract therefore carries `conversationId` on every
 * record, so the surface can label and group by conversation without that lift.
 */
export async function loadDelegations(
  conversationId?: string,
  deps: { invokeFn?: InvokeFn; backend?: () => boolean } = {},
): Promise<DelegationFeed> {
  const backend = deps.backend ?? hasBackend;
  const call = deps.invokeFn ?? ((cmd, args) => invoke(cmd, args));
  if (!backend()) {
    return { state: 'unavailable', reason: 'no_backend', detail: 'no Tauri runtime' };
  }
  let raw: unknown;
  try {
    raw = await call(DELEGATION_LIST_COMMAND, { conversationId: conversationId ?? null });
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    return { state: 'unavailable', reason: classifyDelegationFailure(detail), detail };
  }
  const parsed = parseDelegationList(raw);
  if (parsed === null) {
    return {
      state: 'unavailable',
      reason: 'error',
      detail: `${DELEGATION_LIST_COMMAND} returned something this reader will not accept as a delegation list`,
    };
  }
  return { state: 'ready', delegations: parsed };
}
