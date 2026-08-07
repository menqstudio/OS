// Phase-9 (Integrations) — reachability probing and connector declaration, honestly.
//
// THE PROBLEM THIS SOLVES
// ----------------------
// "Test connection" buttons are the most-lied-to control in software: the common
// implementation flips a local flag, waits, and turns green. This one cannot, because it
// never decides the answer — it asks the backend and then refuses to upgrade anything it
// gets back. Only a literal `reachable: true` from a real reply becomes `reachable`.
// Every failure mode is preserved with its verbatim reason, and the three *different*
// kinds of failure stay distinguishable:
//
//   we could not ask at all   → `unsupported`     (a fact about this build)
//   we asked, learned nothing → `indeterminate`   (a fact about the attempt)
//   we asked, it said no      → `unreachable`     (a fact about the service)
//
// WHAT ACTUALLY HAPPENS TODAY
// ---------------------------
// Neither command below exists. `src-tauri/src/commands.rs` implements exactly two
// integration commands — `list_integrations` and `set_integration_status` — and
// `src-tauri/capabilities/default.json` grants exactly the matching two permissions
// (`allow-list-integrations`, `allow-set-integration-status`). A window capability set is
// deny-by-default, so an ungranted command is refused by the wall with
// `"<cmd> not allowed. Permissions associated with this command: "` before any Rust runs.
//
// That refusal is REAL, so the honest report is produced by really attempting the call and
// classifying the real refusal — not by hard-coding "unsupported". The moment the backend
// ships `probe_integration` and its capability grant, this same code path starts returning
// genuine answers with no UI change. (At that point these two wrappers should move into
// `services/desktop.ts`, the typed IPC boundary, alongside `listIntegrations`; they live
// here only because that boundary has nothing to wrap yet.)
//
// The probe is ALWAYS user-initiated. Nothing here runs on mount, so the page never
// generates capability-wall noise on its own.

import { invoke } from '@tauri-apps/api/core';
import type { Integration } from '../domain/entities';
import type { Reachability } from './integrationsModel';

/** The backend command that would ask the engine/operator to contact the connector.
 *  Not implemented and not granted today — see the header. */
export const PROBE_COMMAND = 'probe_integration';

/** The backend command that would append a connector to the registry. `repo.rs` has
 *  `integrations::create`, but no `#[tauri::command]` exposes it and no capability
 *  grants it, so the desktop cannot declare a connector today. */
export const DECLARE_COMMAND = 'create_integration';

/** Injectable IPC for tests. Production is Tauri's `invoke`; nothing else is simulated. */
export type Transport = (command: string, args: Record<string, unknown>) => Promise<unknown>;

const tauriTransport: Transport = (command, args) => invoke(command, args);

interface Options {
  transport?: Transport;
  /** Clock injection so a test can assert the recorded timestamp. */
  now?: () => string;
}

const isoNow = () => new Date().toISOString();

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Does this rejection mean "this build cannot run that command", as opposed to "the
 * external service is down"? Tauri's capability wall answers `"<cmd> not allowed.
 * Permissions associated with this command: "`, and an unregistered command answers
 * `"Command <cmd> not found"`.
 *
 * The distinction is the whole point: a missing feature must never be reported to the
 * owner as a broken integration. Anything this does NOT match stays `indeterminate`,
 * which is the conservative side — an unclassified error is never promoted into a
 * statement about the service either.
 */
export function isCapabilityRefusal(message: string): boolean {
  return /not allowed|not found|unknown command|permissions associated|no such command/i.test(message);
}

/**
 * Turn a raw probe reply into a reachability fact, FAIL-CLOSED.
 *
 * `reachable` must be the literal boolean `true`. Not `'true'`, not `1`, not a truthy
 * object — those are exactly the shapes a confused or hostile backend produces, and each
 * one of them would otherwise paint a green "connected" badge for free.
 */
export function parseProbeReply(raw: unknown, at: string): Reachability {
  if (!isRecord(raw)) {
    return {
      state: 'indeterminate',
      reason: `${PROBE_COMMAND} reply was not an object`,
      checkedAt: at,
    };
  }
  const detail = typeof raw.detail === 'string' && raw.detail.trim() !== '' ? raw.detail : undefined;
  if (raw.reachable === true) {
    return { state: 'reachable', reason: detail, checkedAt: at };
  }
  if (raw.reachable === false) {
    return {
      state: 'unreachable',
      reason: detail ?? 'the backend reported the connector did not answer',
      checkedAt: at,
    };
  }
  // Present-but-wrong-type, or absent entirely. Either way we learned nothing.
  return {
    state: 'indeterminate',
    reason: `${PROBE_COMMAND} reply carried no boolean \`reachable\` field`,
    checkedAt: at,
  };
}

/**
 * Ask the backend to contact one connector and report what genuinely came back.
 *
 * The desktop itself opens no socket and holds no credential — it asks the governed
 * backend to, which is the Phase-9 boundary. This function never throws: every outcome,
 * including the capability wall, is a typed `Reachability` carrying its real reason.
 */
export async function probeIntegration(id: string, opts: Options = {}): Promise<Reachability> {
  const transport = opts.transport ?? tauriTransport;
  const at = (opts.now ?? isoNow)();
  try {
    const raw = await transport(PROBE_COMMAND, { id });
    return parseProbeReply(raw, at);
  } catch (e) {
    const reason = messageOf(e);
    return {
      state: isCapabilityRefusal(reason) ? 'unsupported' : 'indeterminate',
      reason,
      checkedAt: at,
    };
  }
}

// ── Declaring a connector ────────────────────────────────────────────────────────────

/**
 * The result of trying to add a connector to the registry.
 *
 *  - `ok`           the backend really returned a well-formed connector record
 *  - `unsupported`  this build cannot declare connectors (no command / no grant)
 *  - `invalid`      the input was rejected here, before any call
 *  - `refused`      the backend was reached and said no, or answered with nonsense
 */
export type DeclareOutcome =
  | { ok: true; integration: Integration }
  | { ok: false; kind: 'unsupported' | 'invalid' | 'refused'; reason: string };

/**
 * Validate a raw reply as a connector record, FAIL-CLOSED. A reply that is not a
 * complete record is `refused`, never silently rendered as a new row — a fabricated
 * connector in the registry is exactly the lie this whole page is built to avoid.
 */
export function parseDeclareReply(raw: unknown): DeclareOutcome {
  if (!isRecord(raw)) {
    return { ok: false, kind: 'refused', reason: `${DECLARE_COMMAND} reply was not an object` };
  }
  const str = (k: string) => (typeof raw[k] === 'string' ? (raw[k] as string) : null);
  const id = str('id');
  const name = str('name');
  const provider = str('provider');
  const status = str('status');
  const createdAt = str('createdAt');
  const updatedAt = str('updatedAt');
  if (!id || !name || !provider || !status || createdAt === null || updatedAt === null) {
    return {
      ok: false,
      kind: 'refused',
      reason: `${DECLARE_COMMAND} reply was not a complete connector record`,
    };
  }
  return { ok: true, integration: { id, name, provider, status, createdAt, updatedAt } };
}

/**
 * Declare a connector: record that this product knows about an external channel.
 *
 * This declares a *name*, never a credential — there is no field here for one, by
 * design. A newly declared connector starts life not enabled, unconfigured and untested,
 * which is the truth about it.
 */
export async function declareIntegration(
  name: string,
  provider: string,
  opts: Options = {},
): Promise<DeclareOutcome> {
  const n = name.trim();
  const p = provider.trim();
  if (n === '') return { ok: false, kind: 'invalid', reason: 'name is required' };
  if (p === '') return { ok: false, kind: 'invalid', reason: 'provider is required' };
  const transport = opts.transport ?? tauriTransport;
  try {
    const raw = await transport(DECLARE_COMMAND, { name: n, provider: p });
    return parseDeclareReply(raw);
  } catch (e) {
    const reason = messageOf(e);
    return {
      ok: false,
      kind: isCapabilityRefusal(reason) ? 'unsupported' : 'refused',
      reason,
    };
  }
}
