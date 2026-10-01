import { useCallback, useEffect, useMemo, useState } from 'react';
import { desktop, type WriteRecord, type WriteRecordState } from '../services/desktop';
import type { Lang } from '../domain/enums';
import {
  STR, divergedNotice, deletedPresentNotice, unreadableNotice,
} from './writeRecord.strings';

// ---------------------------------------------------------------------------
// The LOCAL WRITE RECORD reader — shared by the Memory and Knowledge pages so both
// surfaces say exactly the same thing about exactly the same backend.
//
// The backend (`core/src/local_write_record.rs`, migration 0021) appends a record for
// every memory/knowledge write INSIDE that write's own transaction. The record pins the
// row's content — `content_sha256` over a canonical sorted-key envelope — plus the
// previous record's hash, forming a chain from sequence 1 that three DATABASE TRIGGERS
// keep append-only. Recomputing the digest from the row therefore detects a later edit
// made outside the app.
//
// That is the whole claim. Nothing here is signed: no key, no manifest, no authority,
// no containment, and the record is written by the same local process that performs the
// write — so it attests CONTENT and never the writer. This module therefore renders
// "recorded" / "content diverged" / "deleted, yet present" / "no record", and must never
// borrow the governed-receipt vocabulary or a green tick a reader would file next to it.
//
// Two distinctions this module exists to keep:
//
//   1. `content_diverged` is NOT a shade of `recorded`. It gets its own tone, its own
//      glyph and its own sentence, because it is the one state that says a row was
//      edited behind the app's back.
//   2. "could not read the record" is NOT "there is no record". A read that faulted is
//      reported as a fault; collapsing it into `unrecorded` is how a broken reader reads
//      as an empty, innocent ledger. A reply in an unrecognised shape is likewise a
//      fault, never an absence.
// ---------------------------------------------------------------------------

/** Which store a row belongs to — picks the read-only command pair. */
export type WriteRecordSubject = 'memory' | 'knowledge';

/**
 * One row's record read. `read` carries the backend's own four-state answer; the other
 * two phases are about the READ, not about the ledger, and are never merged into it.
 */
export type WriteRecordRead =
  | { phase: 'reading' }
  | { phase: 'unreadable'; reason: string }
  | { phase: 'read'; state: WriteRecordState };

/** The distinct things this surface can say. One class, one label, one sentence each. */
export type WriteRecordKind =
  | 'reading'
  | 'unreadable'
  | 'recorded'
  | 'diverged'
  | 'deletedPresent'
  | 'unrecorded';

const L = (k: keyof typeof STR, lang: Lang): string => STR[k][lang] ?? STR[k].en;

// --- parsing (fail-closed) --------------------------------------------------

function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null;
}

/** Validate a record verbatim. A field missing or mistyped makes the whole reply
 *  uninterpretable — we do not guess a default, because a guessed record is a
 *  fabricated one. */
function parseRecord(raw: unknown): WriteRecord | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const id = str(o.id);
  const subjectId = str(o.subjectId);
  const contentSha256 = str(o.contentSha256);
  const prevRecordSha256 = str(o.prevRecordSha256);
  const recordSha256 = str(o.recordSha256);
  const recordedAt = str(o.recordedAt);
  const subjectKind = str(o.subjectKind);
  const operation = str(o.operation);
  if (
    id === null || subjectId === null || contentSha256 === null || prevRecordSha256 === null ||
    recordSha256 === null || recordedAt === null || typeof o.seq !== 'number' ||
    (subjectKind !== 'memory_entry' && subjectKind !== 'knowledge_note') ||
    (operation !== 'created' && operation !== 'updated' && operation !== 'deleted')
  ) {
    return null;
  }
  return {
    id, seq: o.seq, subjectKind, subjectId, operation,
    contentSha256, prevRecordSha256, recordSha256, recordedAt,
  };
}

/**
 * Parse the backend's `SubjectState`. Returns `null` for anything it does not recognise,
 * which the caller reports as a READ FAULT — never as `unrecorded`.
 */
export function parseWriteRecordState(raw: unknown): WriteRecordState | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const o = raw as Record<string, unknown>;
  switch (o.state) {
    case 'unrecorded':
      return { state: 'unrecorded' };
    case 'recorded': {
      const record = parseRecord(o.record);
      return record ? { state: 'recorded', record } : null;
    }
    case 'deleted_but_present': {
      const record = parseRecord(o.record);
      return record ? { state: 'deleted_but_present', record } : null;
    }
    case 'content_diverged': {
      const record = parseRecord(o.record);
      const actual = str(o.actual_content_sha256);
      return record && actual !== null
        ? { state: 'content_diverged', record, actual_content_sha256: actual }
        : null;
    }
    default:
      return null;
  }
}

/** Collapse a read into the single thing the UI renders for it. */
export function writeRecordKind(read: WriteRecordRead | undefined): WriteRecordKind {
  if (!read) return 'reading';
  if (read.phase === 'reading') return 'reading';
  if (read.phase === 'unreadable') return 'unreadable';
  switch (read.state.state) {
    case 'recorded': return 'recorded';
    case 'content_diverged': return 'diverged';
    case 'deleted_but_present': return 'deletedPresent';
    case 'unrecorded': return 'unrecorded';
  }
}

const BADGE_KEY: Record<WriteRecordKind, keyof typeof STR> = {
  reading: 'badgeReading',
  unreadable: 'badgeUnreadable',
  recorded: 'badgeRecorded',
  diverged: 'badgeDiverged',
  deletedPresent: 'badgeDeletedPresent',
  unrecorded: 'badgeUnrecorded',
};

const DETAIL_KEY: Record<WriteRecordKind, keyof typeof STR> = {
  reading: 'detailReading',
  unreadable: 'detailUnreadable',
  recorded: 'detailRecorded',
  diverged: 'detailDiverged',
  deletedPresent: 'detailDeletedPresent',
  unrecorded: 'detailUnrecorded',
};

/** Non-colour carriers, so the states stay distinguishable without colour vision.
 *  `unrecorded` gets a neutral dash on purpose — it is an absence, not an alarm. */
const GLYPH: Record<WriteRecordKind, string> = {
  reading: '◌',
  unreadable: '⚑',
  recorded: '◈',
  diverged: '⚠',
  deletedPresent: '⊘',
  unrecorded: '–',
};

export function writeRecordLabel(read: WriteRecordRead | undefined, lang: Lang): string {
  return L(BADGE_KEY[writeRecordKind(read)], lang);
}

export function writeRecordDetail(read: WriteRecordRead | undefined, lang: Lang): string {
  return L(DETAIL_KEY[writeRecordKind(read)], lang);
}

/** How many rows sit in each state. Used for the page-level notice. */
export function writeRecordCounts(reads: Iterable<WriteRecordRead>): Record<WriteRecordKind, number> {
  const out: Record<WriteRecordKind, number> = {
    reading: 0, unreadable: 0, recorded: 0, diverged: 0, deletedPresent: 0, unrecorded: 0,
  };
  for (const r of reads) out[writeRecordKind(r)] += 1;
  return out;
}

// --- reading ----------------------------------------------------------------

const errText = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** Sentinel reason for a reply this build cannot interpret — translated at render time
 *  rather than baked into the state, so the fault reads in the user's language. */
export const UNRECOGNISED_REPLY = '\u0000unrecognised-reply';

/** The human sentence for an unreadable read's reason. */
export function writeRecordReason(reason: string, lang: Lang): string {
  return reason === UNRECOGNISED_REPLY ? L('unrecognisedReply', lang) : reason;
}

/**
 * Read one record state per row id, each independently, so ONE failing read is reported
 * as that row's fault and never darkens (or whitewashes) the others.
 *
 * The commands are read-only (`memory_write_record_state` / `knowledge_write_record_state`).
 * `reload()` must be called after any accepted write: a write appends a new record, so a
 * cached state would otherwise describe the row as it used to be.
 */
export function useWriteRecordStates(
  subject: WriteRecordSubject,
  ids: readonly string[],
): { byId: ReadonlyMap<string, WriteRecordRead>; reload: () => void } {
  const [byId, setById] = useState<ReadonlyMap<string, WriteRecordRead>>(new Map());
  const [tick, setTick] = useState(0);
  const key = ids.join('\u0000');

  useEffect(() => {
    const list = key === '' ? [] : key.split('\u0000');
    if (list.length === 0) {
      setById(new Map());
      return;
    }
    let alive = true;
    setById(new Map(list.map((id): [string, WriteRecordRead] => [id, { phase: 'reading' }])));
    const read = subject === 'memory'
      ? desktop.memoryWriteRecordState
      : desktop.knowledgeWriteRecordState;
    const put = (id: string, r: WriteRecordRead) => {
      if (!alive) return;
      setById((prev) => new Map(prev).set(id, r));
    };
    for (const id of list) {
      read(id).then(
        (raw: unknown) => {
          const state = parseWriteRecordState(raw);
          put(id, state
            ? { phase: 'read', state }
            // Fail closed: an answer we cannot interpret is a fault, not "no record".
            : { phase: 'unreadable', reason: UNRECOGNISED_REPLY });
        },
        (e: unknown) => put(id, { phase: 'unreadable', reason: errText(e) }),
      );
    }
    return () => { alive = false; };
  }, [subject, key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { byId, reload };
}

// --- presentation -----------------------------------------------------------

const shortHash = (h: string): string => (h.length > 16 ? `${h.slice(0, 16)}…` : h);

/**
 * The per-row badge. Always rendered for a row, in every state, so the absence of a
 * claim is itself visible. The state's word is real text (not colour alone), and the
 * class carries the tone — `diverged` is deliberately loud.
 */
export function WriteRecordBadge(
  { read, lang }: { read: WriteRecordRead | undefined; lang: Lang },
) {
  const kind = writeRecordKind(read);
  return (
    <span
      className={`wrec-badge wrec-badge--${kind}`}
      data-wrec={kind}
      title={writeRecordDetail(read, lang)}
    >
      <span className="wrec-glyph" aria-hidden="true">{GLYPH[kind]}</span>
      {L(BADGE_KEY[kind], lang)}
    </span>
  );
}

function opLabel(op: WriteRecord['operation'], lang: Lang): string {
  return L(op === 'created' ? 'opCreated' : op === 'updated' ? 'opUpdated' : 'opDeleted', lang);
}

/**
 * The full statement for one selected row: what the record says, what it cannot say, and
 * the raw material behind it (chain position, write, digests) so the claim is checkable
 * rather than decorative.
 */
export function WriteRecordPanel(
  { read, lang, fmtDate }:
  { read: WriteRecordRead | undefined; lang: Lang; fmtDate?: (raw: string) => string },
) {
  const kind = writeRecordKind(read);
  const record = read?.phase === 'read' && 'record' in read.state ? read.state.record : null;
  const diverged = read?.phase === 'read' && read.state.state === 'content_diverged'
    ? read.state.actual_content_sha256
    : null;

  return (
    <div className={`wrec-panel wrec-panel--${kind}`} data-wrec={kind} role="status">
      <div className="wrec-head">
        <span className="wrec-title">{L('panelTitle', lang)}</span>
        <WriteRecordBadge read={read} lang={lang} />
      </div>
      <p className="wrec-detail">{writeRecordDetail(read, lang)}</p>

      {read?.phase === 'unreadable' && (
        <div className="wrec-fields">
          <span className="wrec-row">
            <i>{L('fieldReason', lang)}</i>
            <b className="wrec-hash">{writeRecordReason(read.reason, lang)}</b>
          </span>
        </div>
      )}

      {record && (
        <div className="wrec-fields">
          <span className="wrec-row">
            <i>{L('fieldRecordedAt', lang)}</i>
            <b>{fmtDate ? fmtDate(record.recordedAt) : record.recordedAt}</b>
          </span>
          <span className="wrec-row">
            <i>{L('fieldChainPos', lang)}</i>
            <b>{record.seq}</b>
          </span>
          <span className="wrec-row">
            <i>{L('fieldWrite', lang)}</i>
            <b>{opLabel(record.operation, lang)}</b>
          </span>
          <span className="wrec-row">
            <i>{L('fieldRecordedHash', lang)}</i>
            <b className="wrec-hash" title={record.contentSha256}>{shortHash(record.contentSha256)}</b>
          </span>
          {diverged !== null && (
            <span className="wrec-row wrec-row--diverged">
              <i>{L('fieldRowHashNow', lang)}</i>
              <b className="wrec-hash" title={diverged}>{shortHash(diverged)}</b>
            </span>
          )}
        </div>
      )}

      {/* The ceiling, on the panel itself: content, never the writer. */}
      <p className="wrec-scope">{L('panelScope', lang)}</p>
    </div>
  );
}

/**
 * Page-level summary. Only the states that need acting on are named — a page of ordinary
 * `recorded` / `unrecorded` rows raises nothing, because neither is news. Polite
 * (`role="status"`): it reports a standing condition, it does not interrupt.
 */
export function WriteRecordNotice(
  { reads, lang }: { reads: ReadonlyMap<string, WriteRecordRead>; lang: Lang },
) {
  // The prop is the MAP the hook returns, whose identity changes only when a read lands. Both
  // callers used to pass `byId.values()`: a new iterator object on every render, so this memo
  // could never hit — and a ONE-SHOT one, so anything that consumed it twice would have counted
  // zero rows and hidden the notice. Iterating inside the memo makes both impossible.
  const counts = useMemo(() => writeRecordCounts(reads.values()), [reads]);
  const lines: { key: string; text: string; tone: string }[] = [];
  if (counts.diverged > 0) {
    lines.push({ key: 'diverged', text: divergedNotice(lang, counts.diverged), tone: 'diverged' });
  }
  if (counts.deletedPresent > 0) {
    lines.push({
      key: 'deletedPresent',
      text: deletedPresentNotice(lang, counts.deletedPresent),
      tone: 'deletedPresent',
    });
  }
  if (counts.unreadable > 0) {
    lines.push({ key: 'unreadable', text: unreadableNotice(lang, counts.unreadable), tone: 'unreadable' });
  }
  if (lines.length === 0) return null;

  return (
    <div className="wrec-notice" role="status">
      <b className="wrec-notice-title">{L('noticeTitle', lang)}</b>
      <ul className="wrec-notice-list">
        {lines.map((l) => (
          <li key={l.key} className={`wrec-notice-line wrec-notice-line--${l.tone}`} data-wrec={l.tone}>
            <span className="wrec-glyph" aria-hidden="true">{GLYPH[l.tone as WriteRecordKind]}</span>
            {l.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Styles for the surface above. Appended by each host page to its own `<style>` block
 *  so the tones live with the component rather than being re-invented per page. */
export const WRITE_RECORD_CSS = `
.wrec-badge { display: inline-flex; align-items: center; gap: 5px; height: 20px; padding: 0 8px;
  border-radius: var(--r-pill); border: 1px solid rgb(var(--line-rgb)/.8);
  font-family: var(--f-mono); font-size: var(--t-micro); letter-spacing: .02em;
  color: var(--ink-muted); background: transparent; white-space: nowrap; }
.wrec-badge .wrec-glyph { font-size: 11px; line-height: 1; }
.wrec-badge--recorded { color: var(--mint); border-color: rgb(var(--mint-rgb)/.34);
  background: rgb(var(--mint-rgb)/.08); }
/* An absence, drawn as an absence: no colour, no alarm, a dashed outline. */
.wrec-badge--unrecorded { color: var(--ink-muted); border-style: dashed;
  border-color: rgb(var(--line-rgb)/.9); background: transparent; }
.wrec-badge--reading { color: var(--ink-muted); opacity: .62; }
/* A read that faulted — amber, distinct from both "recorded" and "no record". */
.wrec-badge--unreadable { color: var(--warning); border-color: rgb(var(--warning-rgb)/.5);
  background: rgb(var(--warning-rgb)/.1); }
/* The one that matters: a row edited out of band. Loud on purpose. */
.wrec-badge--diverged { color: var(--danger); border-color: rgb(var(--danger-rgb)/.6);
  background: rgb(var(--danger-rgb)/.16); font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; box-shadow: 0 0 0 1px rgb(var(--danger-rgb)/.22); }
.wrec-badge--deletedPresent { color: var(--danger); border-color: rgb(var(--danger-rgb)/.5);
  background: rgb(var(--danger-rgb)/.1); font-weight: 700; }

.wrec-panel { display: grid; gap: 7px; padding: 10px 12px; border-radius: var(--r);
  border: 1px solid rgb(var(--line-rgb)/.75); background: rgb(var(--raised-rgb)/.4); }
.wrec-panel--diverged { border-color: rgb(var(--danger-rgb)/.5); background: rgb(var(--danger-rgb)/.09); }
.wrec-panel--deletedPresent { border-color: rgb(var(--danger-rgb)/.42); background: rgb(var(--danger-rgb)/.07); }
.wrec-panel--unreadable { border-color: rgb(var(--warning-rgb)/.42); background: rgb(var(--warning-rgb)/.07); }
.wrec-panel--unrecorded { border-style: dashed; }
.wrec-head { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); }
.wrec-title { font-size: var(--t-micro); text-transform: uppercase; letter-spacing: .14em;
  font-weight: 700; color: var(--ink-muted); }
.wrec-detail { margin: 0; font-size: var(--t-small); line-height: 1.5; color: var(--ink); }
.wrec-panel--diverged .wrec-detail, .wrec-panel--deletedPresent .wrec-detail { color: var(--danger); font-weight: 600; }
.wrec-scope { margin: 0; font-size: 11px; line-height: 1.45; color: var(--ink-muted); }
.wrec-fields { display: grid; gap: 3px; }
.wrec-row { display: flex; align-items: baseline; gap: 8px; font-family: var(--f-mono); font-size: 11px; }
.wrec-row i { font-style: normal; color: var(--ink-muted); min-width: 96px; }
.wrec-row b { font-weight: 600; color: var(--ink); }
.wrec-row--diverged b { color: var(--danger); }
.wrec-hash { word-break: break-all; }

.wrec-notice { display: grid; gap: 5px; margin-bottom: var(--s4); padding: 10px 12px;
  border: 1px solid rgb(var(--line-rgb)/.8); border-radius: var(--r);
  background: rgb(var(--raised-rgb)/.45); font-size: var(--t-small); }
.wrec-notice-title { font-size: var(--t-micro); text-transform: uppercase; letter-spacing: .14em;
  color: var(--ink-muted); }
.wrec-notice-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.wrec-notice-line { display: flex; align-items: baseline; gap: 7px; }
.wrec-notice-line--diverged, .wrec-notice-line--deletedPresent { color: var(--danger); font-weight: 600; }
.wrec-notice-line--unreadable { color: var(--warning); }
`;
