// Where the chat's delegation LEDGER gets its records -- and why, today, it still gets none.
//
// This module does not simulate a feed. It asks the backend for one and reports exactly what
// came back, including "there is no such command".
//
// ---- What changed, and what did NOT ------------------------------------------------
// The LIVE path now exists: a running turn reports each delegation on the `StreamEvent`
// channel (`commands.rs::delegation_frame`), and `Conversations.tsx` folds those frames into
// the surface as they happen. That is a feed, not a history.
//
// The READ path is still missing. No command persists or replays a delegation, so
// `loadDelegations` resolves to `unavailable` carrying the backend's own words, and the
// surface prints them. That honesty is load-bearing precisely BECAUSE live cards now appear
// above it: without it, a list holding one turn's delegations looks like the complete record
// of a conversation, and the owner would read an empty list after a reload as "Bro delegated
// nothing" rather than "nothing was ever stored". Do not remove it because a live path exists.
//
// The day `list_delegations` exists, this file needs no change -- the probe succeeds and the
// same fail-closed reader parses the reply.
//
// PLACEMENT NOTE (for the backend slice): `services/desktop.ts` is "the single typed boundary
// between React and the Tauri backend", and this `invoke` belongs there beside `streamReply`.
// It sits here only because `services/` was outside the originating task's edit scope. When the
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
 * `Conversations.tsx` now renders the surface itself and passes the thread it is actually
 * showing, so the probe is scoped to one conversation rather than asking for everything and
 * sorting it out afterwards. It stays OPTIONAL for the case with no thread open (and for the
 * direct unit tests below), where `null` goes out and the backend would decide what that means.
 * Every record also carries its own `conversationId`, so a reply can still be checked rather
 * than assumed to match what was asked for.
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
