// Honest probes behind the two Settings values that used to be typed into the source
// instead of read from anything.
//
// 1. SYSTEM IDENTITY. The "System" panel printed `MENQ OS` and `v0.9` as literals under
//    a row labelled "Version". The running build is `BroPS` at `0.1.0` (tauri.conf.json /
//    package.json), so the row was not merely unestablished — it was wrong, and being a
//    literal it could never notice a release. `readAppIdentity` asks the running build
//    instead, through the Tauri app plugin (`app|version` / `app|name`, granted by
//    `core:default` in capabilities/default.json). When the build does not answer — no
//    desktop runtime, an ACL denial, a non-string reply — it returns `unreported` and the
//    page shows nothing rather than a comfortable guess.
//
// 2. PREFERENCE PERSISTENCE. Appearance claimed "Preferences are saved to this device".
//    Theme and language are written by app/store.tsx through a `try { localStorage… }
//    catch { /* ignore */ }`, so when storage is unwritable the write is swallowed, the
//    claim is false, and the setting silently reverts on the next reload. `probePreferenceStorage`
//    performs a real write→read-back→delete so the page can state which of the two is true.
//
// Neither probe asserts anything about governance, the engine, or the wall.

import { getName, getVersion } from '@tauri-apps/api/app';
import { hasBackend } from '../services/desktop';

/** What the running build reported about itself. `unreported` is a first-class outcome:
 *  it is the honest state whenever the build did not answer, and it must render as an
 *  absent value, never as a default string. */
export type AppIdentity =
  | { state: 'reported'; name: string; version: string }
  | { state: 'unreported'; reason: string };

/** Ask the running application build for its own name and version.
 *
 *  Fail-closed in the honesty sense: BOTH values must come back as non-empty strings,
 *  otherwise the whole identity is `unreported` — a half-known identity would let one
 *  real field lend credibility to a missing one. Never rejects. */
export async function readAppIdentity(): Promise<AppIdentity> {
  if (!hasBackend()) {
    return { state: 'unreported', reason: 'no_desktop_backend' };
  }
  try {
    const [name, version] = await Promise.all([getName(), getVersion()]);
    const n = typeof name === 'string' ? name.trim() : '';
    const v = typeof version === 'string' ? version.trim() : '';
    if (!n || !v) {
      return { state: 'unreported', reason: 'build_reported_no_name_or_version' };
    }
    return { state: 'reported', name: n, version: v };
  } catch (e) {
    return { state: 'unreported', reason: e instanceof Error ? e.message : String(e) };
  }
}

/** Whether a preference written on this device actually survives being written. */
export type PreferenceStorage =
  | { state: 'persisted' }
  | { state: 'not_persisted'; reason: string };

/** A key of our own, so the probe can never disturb a real stored preference. */
const PROBE_KEY = 'brops.settings.persistence-probe';

/**
 * Write a token, read it back, delete it. Anything other than an exact round-trip —
 * a throwing `localStorage` (disabled storage, a partitioned/blocked context, quota),
 * a missing API, a value that does not come back — means the preferences the page
 * offers are not being stored, and the page must say so instead of resetting quietly.
 */
export function probePreferenceStorage(): PreferenceStorage {
  try {
    if (typeof localStorage === 'undefined' || localStorage === null) {
      return { state: 'not_persisted', reason: 'no_local_storage_in_this_window' };
    }
    const token = `probe-${Date.now()}-${Math.random()}`;
    localStorage.setItem(PROBE_KEY, token);
    const readBack = localStorage.getItem(PROBE_KEY);
    localStorage.removeItem(PROBE_KEY);
    if (readBack !== token) {
      return { state: 'not_persisted', reason: 'write_did_not_read_back' };
    }
    return { state: 'persisted' };
  } catch (e) {
    return { state: 'not_persisted', reason: e instanceof Error ? e.message : String(e) };
  }
}
