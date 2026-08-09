// Pure model helpers for the Files bench (`Files.tsx`).
//
// Everything here is a function of values the page ACTUALLY received from the
// real backend commands in `src-tauri/src/files.rs` — `list_dir` (a `DirListing`)
// and `read_file` (a `FileContent`). Nothing invents a fact: where the backend
// reports nothing, these return an explicit "not established" result rather than
// a plausible-looking default.
//
// Extracted from the page so each rule can be unit-tested on its own.

import type { DirEntry, FileContent } from '../domain/entities';

// ── guard vocabulary ────────────────────────────────────────────────────────
//
// A file's guard state is only known once the file has actually been opened
// through `read_file`. `unknown` is therefore the honest starting state — the
// previous default was `open`, which announced "open" (in the row's aria-label)
// for every file the page had never read. Directories are `open` only in the
// sense that they can be navigated, which `list_dir` did establish.
export type Guard = 'unknown' | 'open' | 'read' | 'sealed';

/**
 * A guard denial reads like a permission / scope refusal from the backend or the
 * engine wall. Distinguishing it from a plain transport failure lets the page
 * render the honest `sealed` state only when the open was actually refused.
 *
 * The specific phrases are the EXACT strings the Rust backend returns on a
 * wall/scope refusal — today that is "the configured files root is not allowed"
 * (the `BROPS_FILES_ROOT` clamp in `files_root`). Availability / not-found
 * strings ("workspace is unavailable", "cannot read file") are deliberately NOT
 * matched — those are transport failures, not guard denials.
 *
 * "path is outside the allowed workspace" and "access to this path is blocked"
 * USED to be matched here and are gone on purpose. `confine_in`/`confine_under`
 * now return one single string, `"path is not accessible in this workspace"`,
 * for every path refusal — does-not-exist, cannot-canonicalize, outside-the-root
 * and denylisted alike — because the differing wordings made the backend an
 * existence oracle for any absolute path a compromised renderer cared to try.
 *
 * That string is NOT matched here, and the omission is the honest reading, not
 * an oversight: the backend deliberately no longer establishes WHICH of those
 * four happened, so the page cannot claim `sealed` ("the guard refused this")
 * for what may simply be a file that was deleted between the listing and the
 * open. Per this module's rule, an unestablished fact stays unestablished.
 */
export function isGuardDenied(message: string): boolean {
  return /denied|not permitted|not allowed|permission|sealed|forbidden|scope|guard/i.test(
    message,
  );
}

// ── sizes ───────────────────────────────────────────────────────────────────

/** Rendered when a size was not established. Distinct from a real `0 B`. */
export const NOT_ESTABLISHED = '—';

export function formatSize(bytes: number | undefined | null): string {
  // Entry sizes can be absent/non-numeric from the backend — never render "NaN KB".
  if (bytes == null || !Number.isFinite(bytes)) return NOT_ESTABLISHED;
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 ? 1 : 0)} ${units[i]}`;
}

// ── why a file came back read-only ──────────────────────────────────────────
//
// `read_file` collapses three different situations into one `readonly: true`
// flag, and the page used to render one flat "can't preview this" line for all
// of them — so "this is a folder/device", "this is 40 MB" and "this is binary"
// were indistinguishable. The backend does return enough to tell them apart, and
// its contract (files.rs `read_text`) is exact:
//
//   * a non-regular file (directory, symlink, device) returns `size_bytes: 0`
//     with empty content — and a genuinely empty REGULAR file is not readonly at
//     all (empty bytes parse as valid UTF-8), so `readonly && size === 0`
//     unambiguously means "not a regular file";
//   * a file over the edit cap returns its real (over-cap) size;
//   * anything else readonly failed the UTF-8 parse, i.e. it is binary.
//
// If `MAX_EDIT_BYTES` in files.rs ever changes, only the boundary between
// `tooLarge` and `binary` moves; nothing here starts asserting something the
// backend did not say.
export const MAX_EDIT_BYTES = 2 * 1024 * 1024;

export type ReadonlyReason = 'notRegular' | 'tooLarge' | 'binary';

/** Why `read_file` reported `readonly`. Only meaningful when `readonly` is true. */
export function readonlyReason(sizeBytes: number | undefined | null): ReadonlyReason {
  if (sizeBytes == null || !Number.isFinite(sizeBytes)) return 'binary';
  if (sizeBytes > MAX_EDIT_BYTES) return 'tooLarge';
  if (sizeBytes === 0) return 'notRegular';
  return 'binary';
}

/**
 * The size `read_file` actually established for this file, or `null` when it did
 * not establish one. A non-regular target is reported as `size_bytes: 0` — that
 * zero is a placeholder, not a measurement, so rendering it as "0 B" would be
 * asserting a size nobody measured.
 */
export function establishedContentSize(data: Pick<FileContent, 'readonly' | 'sizeBytes'>): number | null {
  if (data.readonly && readonlyReason(data.sizeBytes) === 'notRegular') return null;
  if (data.sizeBytes == null || !Number.isFinite(data.sizeBytes)) return null;
  return data.sizeBytes;
}

// ── modified time ───────────────────────────────────────────────────────────
//
// `list_dir` returns `modified` as milliseconds-since-epoch in a string, or
// `null` when the platform did not report one. The page rendered neither, so a
// real value the backend had already established was simply dropped.

/** Parse the backend's `modified` field. Returns `null` when unset/unparseable. */
export function parseModified(raw: string | null | undefined): Date | null {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (s === '') return null;
  const ms = Number(s);
  if (!Number.isFinite(ms)) return null;
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? null : d;
}

// ── ordering ────────────────────────────────────────────────────────────────
//
// `list_dir` returns directories first, then files, each group sorted
// case-insensitively by name. Sorting here is a pure reordering of that real
// listing — it never adds or hides a row — and it keeps the directories-first
// grouping so navigation stays predictable.

export type SortKey = 'name' | 'size' | 'modified';
export type SortDir = 'asc' | 'desc';

function byName(a: DirEntry, b: DirEntry): number {
  return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
}

export function sortEntries(entries: DirEntry[], key: SortKey, dir: SortDir): DirEntry[] {
  const sign = dir === 'desc' ? -1 : 1;
  return [...entries].sort((a, b) => {
    // Directories always first — the backend's own grouping.
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
    if (key === 'name') return sign * byName(a, b);
    if (key === 'size') {
      const av = Number.isFinite(a.sizeBytes) ? a.sizeBytes : 0;
      const bv = Number.isFinite(b.sizeBytes) ? b.sizeBytes : 0;
      return av === bv ? byName(a, b) : sign * (av - bv);
    }
    // modified: entries with no reported time sort last in BOTH directions —
    // "unknown" is not "oldest", so it must never be ordered as if it were.
    const at = parseModified(a.modified)?.getTime();
    const bt = parseModified(b.modified)?.getTime();
    if (at == null && bt == null) return byName(a, b);
    if (at == null) return 1;
    if (bt == null) return -1;
    return at === bt ? byName(a, b) : sign * (at - bt);
  });
}

// ── breadcrumbs ─────────────────────────────────────────────────────────────

/**
 * Reconstruct clickable breadcrumb segments from the REAL current path string
 * (from `list_dir`). Ancestor segments become navigable to their reconstructed
 * path; the last segment is the current directory. No fabrication — every label
 * and target is derived from the real path the backend resolved.
 */
export function crumbSegments(path?: string): { label: string; nav?: string }[] {
  if (!path) return [];
  const sep = path.includes('\\') ? '\\' : '/';
  const segs: { label: string; nav?: string }[] = [];
  let acc = '';
  path.split(sep).forEach((part, i) => {
    if (part === '') { if (i === 0) acc = sep; return; }
    acc = acc === '' || acc === sep ? acc + part : acc + sep + part;
    segs.push({ label: part, nav: acc });
  });
  if (segs.length) segs[segs.length - 1].nav = undefined; // current dir — not a link
  return segs;
}

// ── selection ───────────────────────────────────────────────────────────────

/**
 * What the tray can honestly say about a selection. Only FILES carry a measured
 * size (`list_dir` reports `0` for a directory because it does not walk it), so
 * the byte total covers the selected files and the directory count is reported
 * separately rather than folded into a total that would understate the truth.
 */
export function selectionSummary(selected: DirEntry[]): {
  files: number; folders: number; fileBytes: number;
} {
  let files = 0;
  let folders = 0;
  let fileBytes = 0;
  for (const e of selected) {
    if (e.isDir) { folders += 1; continue; }
    files += 1;
    if (Number.isFinite(e.sizeBytes)) fileBytes += e.sizeBytes;
  }
  return { files, folders, fileBytes };
}
