// Classify why a hard delete came back refused.
//
// SHARED by Library.tsx and Research.tsx. It carries a `research*` module name
// because this task may only add modules named `files*` / `library*` /
// `research*`; there is nothing research-specific in it.
//
// WHY THIS EXISTS. `delete_library_item` and `delete_research_item` are DENIED in
// the window capability set (`src-tauri/capabilities/default.json`:
// `deny-delete-library-item`, `deny-delete-research-item`), and the Rust handlers
// are structural refusals on top of that (`commands::forbidden_hard_delete` —
// they take no `AppState`, so they hold no database handle and cannot remove a
// row even if a grant were flipped by mistake). A refusal is therefore the
// ORDINARY outcome of pressing Delete, not an edge case.
//
// The user-visible consequence of getting this wrong is specific: the row comes
// back. If the page shows a generic "something went wrong", the owner reasonably
// reads that as transient and presses Delete again — forever. So the page has to
// distinguish a PERMANENT policy refusal (retrying cannot succeed) from a failure
// that might be worth retrying, and it can only do that from what the backend
// actually said.
//
// Two different messages can arrive, because two different walls can refuse:
//
//   1. The Tauri ACL refuses BEFORE the handler body runs. That is today's real
//      path, and its message looks like
//        "delete_library_item not allowed. Permissions associated with this command: …"
//   2. The handler's own refusal, if the ACL ever let the call through. It starts
//      with the stable machine prefix `forbidden_command:` (commands.rs
//      `FORBIDDEN_COMMAND_PREFIX`) and states plainly that nothing was deleted.
//
// Anything else is left UNCLASSIFIED on purpose. Guessing "this is policy" from
// an unfamiliar string would be inventing a fact, and it is exactly the mistake
// that makes a transient outage look permanent.

import { hasBackend } from '../services/desktop';

/** The stable machine prefix of a capability-forbidden refusal (commands.rs). */
export const FORBIDDEN_COMMAND_PREFIX = 'forbidden_command';

export type DeleteRefusalKind =
  /** A permanent policy refusal. Retrying cannot succeed. */
  | 'policy'
  /** There is no desktop backend here at all, so no store was ever asked. */
  | 'noBackend'
  /** The store was asked and something else went wrong. May or may not be transient. */
  | 'unknown';

export interface DeleteRefusal {
  kind: DeleteRefusalKind;
  /** The backend's own words, verbatim, for the owner to read. */
  reason: string;
}

function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === 'string') return err;
  if (err == null) return '';
  try {
    return typeof err === 'object' ? JSON.stringify(err) : String(err);
  } catch {
    return String(err);
  }
}

/**
 * True when `message` is one of the two refusals the capability wall produces for
 * a named command. Deliberately narrow: it requires the command name to appear
 * alongside the refusal wording, so an unrelated message that merely contains
 * "not allowed" is not promoted to a permanent verdict.
 */
export function isPolicyRefusal(message: string, command: string): boolean {
  if (message.includes(`${FORBIDDEN_COMMAND_PREFIX}:`)) return true;
  if (!message.includes(command)) return false;
  return /not allowed|not permitted|forbidden|denied|permissions associated with this command/i
    .test(message);
}

/**
 * Classify a rejected delete. `command` is the exact Tauri command name that was
 * invoked (e.g. `delete_library_item`), so the match can be tied to it.
 *
 * `backendPresent` is injectable purely so tests can exercise the no-backend arm;
 * production callers omit it and the real runtime check is used.
 */
export function classifyDeleteRefusal(
  err: unknown,
  command: string,
  backendPresent: boolean = hasBackend(),
): DeleteRefusal {
  const reason = messageOf(err);
  if (isPolicyRefusal(reason, command)) return { kind: 'policy', reason };
  if (!backendPresent) return { kind: 'noBackend', reason };
  return { kind: 'unknown', reason };
}
