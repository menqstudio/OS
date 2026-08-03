import {
  Fragment,
  useCallback, useEffect, useMemo, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  Button, Badge, Skeleton, ErrorState, EmptyState,
  Modal, Textarea, ConfirmDialog,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { useToast } from '../components/toast';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { DirEntry } from '../domain/entities';
import { STR } from './Files.strings';

// Reconstruct clickable breadcrumb segments from the REAL current path string
// (from `listDir`). Ancestor segments become navigable to their reconstructed
// path; the last segment is the current directory. No fabrication — every label
// and target is derived from the real path the backend resolved.
function crumbSegments(path?: string): { label: string; nav?: string }[] {
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

// Per-file guard state, per the §D file guard vocabulary (open / read / sealed).
// It is DERIVED from real engine responses, never fabricated: 'open' is the lawful
// default; a file that reads back `readonly` becomes 'read'; a denied open becomes
// 'sealed' (the blocked state). Directories are always 'open'.
type Guard = 'open' | 'read' | 'sealed';

function formatSize(bytes: number | undefined | null): string {
  // entry sizes can be absent/non-numeric from the backend — never render "NaN KB".
  if (bytes == null || !Number.isFinite(bytes)) return '—';
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

// A guard denial reads like a permission / scope refusal from the backend or the
// engine wall. Distinguishing it from a plain transport failure lets us render the
// honest `blocked` (sealed) state only when the open was actually refused.
function isGuardDenied(message: string): boolean {
  return /denied|not permitted|permission|sealed|forbidden|scope|guard/i.test(message);
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/** View / edit a single text file. Mounts only while a file is being edited, so
 *  the read happens on open and unmounts (discarding edits) on close. This keeps
 *  the original read/write wiring (`readFile`/`writeFile`) intact. */
function FileEditor({ entry, onClose }: { entry: DirEntry; onClose: () => void }) {
  const { t } = useApp();
  const toast = useToast();
  const s = useAsync(() => desktop.readFile(entry.path), [entry.path]);
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Overwriting an existing file is destructive, so — like deletes — it is
  // gated behind an explicit confirmation step.
  const [confirmingSave, setConfirmingSave] = useState(false);

  useEffect(() => {
    if (s.data) {
      setContent(s.data.content);
      setOriginal(s.data.content);
    }
  }, [s.data]);

  const editable = s.data != null && !s.data.readonly;
  const dirty = content !== original;

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      await desktop.writeFile(entry.path, content);
      setOriginal(content);
      toast(t('files.saved'), 'success');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={entry.name} onClose={onClose}>
      {s.loading && s.data === null && <Skeleton rows={6} />}
      {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
      {s.data && !editable && (
        <div className="muted" style={{ marginBottom: 16 }}>{t('files.cantPreview')}</div>
      )}
      {editable && (
        <>
          <Textarea value={content} onChange={(ev) => setContent(ev.target.value)} rows={16} />
          {saveError && <div className="form-error" style={{ marginTop: 8 }}>{saveError}</div>}
        </>
      )}
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('files.close')}</Button>
        {editable && (
          <Button onClick={() => setConfirmingSave(true)} disabled={saving || !dirty}>
            {t('files.save')}
          </Button>
        )}
      </div>
      {confirmingSave && (
        <ConfirmDialog
          title={t('files.save')}
          message={entry.path}
          confirmLabel={t('files.save')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => {
            setConfirmingSave(false);
            save();
          }}
          onCancel={() => setConfirmingSave(false)}
        />
      )}
    </Modal>
  );
}

/** The preview `plane`: mounts per selected file, reads it, and reports the
 *  resolved guard state upward. Renders the `loading`, read-only `read`, editable
 *  `open`, and `blocked` (sealed) states honestly from the real `read_file`
 *  command — no fabricated content. */
function PreviewPlane({ entry, onGuard, onEdit }: {
  entry: DirEntry;
  onGuard: (path: string, guard: Guard) => void;
  onEdit: (entry: DirEntry) => void;
}) {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const s = useAsync(() => desktop.readFile(entry.path), [entry.path]);

  const denied = s.error != null && isGuardDenied(s.error);

  useEffect(() => {
    if (s.data) onGuard(entry.path, s.data.readonly ? 'read' : 'open');
  }, [s.data, entry.path, onGuard]);
  useEffect(() => {
    if (denied) onGuard(entry.path, 'sealed');
  }, [denied, entry.path, onGuard]);

  if (s.loading && s.data === null) return <Skeleton rows={8} />;

  // blocked (sealed): the engine scope guard refused the open. Assertive live
  // region so assistive tech announces the guard reason immediately.
  if (s.error && denied) {
    return (
      <div className="fx-blocked fx-fade" role="alert" aria-live="assertive">
        <div className="fx-blocked-glyph">⛔</div>
        <div className="empty-title">{L('blockedTitle')}</div>
        <div className="muted" style={{ marginTop: 6, maxWidth: 460, marginInline: 'auto' }}>
          {L('blockedHint')} {s.error}
        </div>
        <div style={{ marginTop: 12 }}>
          <Badge tone="danger">{L('guardSealed')}</Badge>
        </div>
      </div>
    );
  }
  // Any other read failure: the shared ErrorState already renders the calm offline
  // state when no backend is present, and a retry otherwise.
  if (s.error) return <ErrorState message={s.error} onRetry={s.reload} />;

  const data = s.data;
  if (!data) return null;

  return (
    <div className="fx-fade">
      <div className="row between" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div className="row" style={{ gap: 8, minWidth: 0 }}>
          <Badge tone={data.readonly ? 'info' : 'success'}>
            {data.readonly ? L('guardRead') : L('guardOpen')}
          </Badge>
          <span className="muted">{formatSize(data.sizeBytes)}</span>
        </div>
        {!data.readonly && (
          <Button small onClick={() => onEdit(entry)}>{L('edit')}</Button>
        )}
      </div>
      {data.readonly ? (
        <div className="muted" style={{ marginBottom: 8 }}>{t('files.cantPreview')}</div>
      ) : (
        <div className="fx-preview-body">
          <pre className="fx-pre">{data.content}</pre>
        </div>
      )}
    </div>
  );
}

export function Files() {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  // undefined path == home directory (resolved by the backend).
  const [path, setPath] = useState<string | undefined>(undefined);
  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<'all' | 'folder' | 'file'>('all');
  const [cursor, setCursor] = useState(0);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<DirEntry | null>(null);
  const [editing, setEditing] = useState<DirEntry | null>(null);
  const [guards, setGuards] = useState<Record<string, Guard>>({});

  const s = useAsync(() => desktop.listDir(path), [path]);
  const queryRef = useRef<HTMLInputElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  const entries = useMemo(() => s.data?.entries ?? [], [s.data]);
  const folderCount = useMemo(() => entries.filter((e) => e.isDir).length, [entries]);
  const fileCount = entries.length - folderCount;

  // fHits: filter the real, already-loaded index by chip (folders/files) and query.
  const hits = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => {
      if (kindFilter === 'folder' && !e.isDir) return false;
      if (kindFilter === 'file' && e.isDir) return false;
      return q === '' || e.name.toLowerCase().includes(q);
    });
  }, [entries, kindFilter, query]);

  const safeCursor = hits.length === 0 ? 0 : Math.min(cursor, hits.length - 1);

  // Navigating into a folder swaps the whole index, so reset the transient
  // per-directory state (cursor, selection, open preview).
  const navigate = useCallback((next: string | undefined) => {
    setPath(next);
    setPreview(null);
    setSelectedPaths(new Set());
    setCursor(0);
  }, []);

  // Filtering can shrink the list under the cursor — keep it in range.
  useEffect(() => { setCursor(0); }, [kindFilter, query]);

  const reportGuard = useCallback((p: string, g: Guard) => {
    setGuards((prev) => (prev[p] === g ? prev : { ...prev, [p]: g }));
  }, []);

  const guardOf = useCallback((e: DirEntry): Guard => {
    if (e.isDir) return 'open';
    return guards[e.path] ?? 'open';
  }, [guards]);

  const openEntry = useCallback((e: DirEntry) => {
    if (e.isDir) navigate(e.path);
    else setPreview(e);
  }, [navigate]);

  const toggleSelect = useCallback((e: DirEntry) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(e.path)) next.delete(e.path);
      else next.add(e.path);
      return next;
    });
  }, []);

  // `/` focuses the filter from anywhere on the page (unless already typing).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && !isTypingTarget(e.target)) {
        e.preventDefault();
        queryRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Keep the focused (active-descendant) row scrolled into view.
  useEffect(() => {
    if (hits.length === 0) return;
    const el = document.getElementById(`fx-row-${safeCursor}`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [safeCursor, hits.length]);

  const onGridKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (hits.length === 0) return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, hits.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
        break;
      case 'Home':
        e.preventDefault();
        setCursor(0);
        break;
      case 'End':
        e.preventDefault();
        setCursor(hits.length - 1);
        break;
      case 'Enter':
        e.preventDefault();
        openEntry(hits[safeCursor]);
        break;
      case ' ':
        e.preventDefault();
        toggleSelect(hits[safeCursor]);
        break;
      default:
        break;
    }
  };

  const filtering = query.trim() !== '' || kindFilter !== 'all';
  const countLabel = filtering
    ? `${hits.length} ${L('hits')} · ${entries.length} ${L('items')}`
    : `${entries.length} ${L('items')}`;

  const chips: { id: 'all' | 'folder' | 'file'; label: string; n: number }[] = [
    { id: 'all', label: L('all'), n: entries.length },
    { id: 'folder', label: L('folders'), n: folderCount },
    { id: 'file', label: L('files'), n: fileCount },
  ];

  const selectedList = useMemo(
    () => entries.filter((e) => selectedPaths.has(e.path)),
    [entries, selectedPaths],
  );

  const segs = useMemo(() => crumbSegments(s.data?.path), [s.data?.path]);

  // Stats derived ENTIRELY from the real, loaded directory listing — never the
  // fabricated guard-tier counts of the mockup (a file's guard is only known
  // after it is actually read, so those are omitted here).
  const statCells: { v: number; label: string; tone: '' | 'info' | 'mint' | 'warn' }[] = [
    { v: entries.length, label: L('items'), tone: '' },
    { v: folderCount, label: L('folders'), tone: 'info' },
    { v: fileCount, label: L('files'), tone: 'mint' },
    filtering
      ? { v: hits.length, label: L('hits'), tone: 'warn' }
      : { v: selectedPaths.size, label: L('selected'), tone: 'warn' },
  ];

  const guardBadge = (g: Guard) => {
    if (g === 'read') return <Badge tone="info">{L('guardRead')}</Badge>;
    if (g === 'sealed') return <Badge tone="danger">{L('guardSealed')}</Badge>;
    return null;
  };

  return (
    <div className="v-files">
      {/* ── HEADER ─────────────────────────────────────────────────────────── */}
      <header className="pageHead reveal">
        <div>
          <span className="eyebrow">{L('eyebrow')}</span>
          <h1>{t('nav.files')}</h1>
          <p className="sub">{t('files.subtitle')}</p>
        </div>
        <div className="right">
          <span className="pill info">{L('indexing')}</span>
          <Mark state="live" size={30} />
        </div>
      </header>

      {/* ── HERO · the data bench ──────────────────────────────────────────── */}
      <section className="bench surface soft lg hud reveal" aria-label={L('bench')}>
        <span className="bracket tl" aria-hidden="true" />
        <span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" />
        <span className="bracket br" aria-hidden="true" />

        {/* command bar — real breadcrumb + filter + kind chips + actions */}
        <div className="bench-bar">
          <nav className="crumb" aria-label={L('path')}>
            {segs.length === 0 ? (
              <b aria-current="page">{s.loading ? t('state.loading') : L('home')}</b>
            ) : segs.map((seg, i) => (
              <Fragment key={seg.nav ?? `cur-${seg.label}`}>
                {i > 0 && <i aria-hidden="true">/</i>}
                {seg.nav ? (
                  <button type="button" className="crumb-seg" onClick={() => navigate(seg.nav)}>
                    {seg.label}
                  </button>
                ) : (
                  <b aria-current="page">{seg.label}</b>
                )}
              </Fragment>
            ))}
          </nav>

          <div className="fsearch">
            <span className="fs-ic" aria-hidden="true">⌕</span>
            <input
              ref={queryRef}
              className="fs-input"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={L('filter')}
              aria-label={L('filter')}
              autoComplete="off"
              spellCheck={false}
            />
            <span className="fs-hits mono">{hits.length}/{entries.length}</span>
          </div>

          <div className="fchips" role="group" aria-label={L('kinds')}>
            {chips.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`chip${kindFilter === c.id ? ' on' : ''}`}
                aria-pressed={kindFilter === c.id}
                onClick={() => setKindFilter(c.id)}
              >
                {c.label} <span className="fx-chip-n mono">{c.n}</span>
              </button>
            ))}
          </div>

          <div className="fx-actions">
            <button
              type="button"
              className="chip"
              onClick={() => s.data?.parent && navigate(s.data.parent)}
              disabled={!s.data?.parent}
              title={t('files.up')}
              aria-label={t('files.up')}
            >
              ↑
            </button>
            <button type="button" className="chip" onClick={s.reload} title={L('refresh')} aria-label={L('refresh')}>
              ⟳
            </button>
          </div>
        </div>

        {/* aria-live status: announces the current hit count as the filter changes */}
        <div className="fx-count" role="status" aria-live="polite">{countLabel}</div>

        <div className="fx-bench-body">
          {/* ── the real, keyboard-navigable file index ── */}
          <div className="fx-col-list">
            {s.loading && s.data === null && <Skeleton rows={6} />}
            {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
            {s.data && entries.length === 0 && (
              <EmptyState glyph="📁" title={t('files.empty')} />
            )}
            {s.data && entries.length > 0 && hits.length === 0 && (
              <EmptyState glyph="🔍" title={L('noMatch')} hint={L('noMatchHint')} />
            )}
            {s.data && hits.length > 0 && (
              <div
                ref={gridRef}
                className="fx-grid"
                role="grid"
                tabIndex={0}
                aria-label={t('nav.files')}
                aria-activedescendant={`fx-row-${safeCursor}`}
                aria-rowcount={hits.length}
                onKeyDown={onGridKeyDown}
              >
                {hits.map((e, i) => {
                  const g = guardOf(e);
                  const isCursor = i === safeCursor;
                  const isSelected = selectedPaths.has(e.path);
                  const isPreview = preview?.path === e.path;
                  const typeWord = e.isDir ? L('entryFolder') : L('entryFile');
                  const guardWord = g === 'read' ? L('guardRead') : g === 'sealed' ? L('guardSealed') : L('guardOpen');
                  return (
                    <div
                      key={e.path}
                      id={`fx-row-${i}`}
                      role="row"
                      aria-selected={isSelected}
                      aria-label={`${e.name}, ${typeWord}, ${guardWord}`}
                      className={`fx-row${isCursor ? ' fx-row--cursor' : ''}${isSelected ? ' fx-row--selected' : ''}${isPreview ? ' fx-row--preview' : ''}`}
                      onClick={() => { setCursor(i); openEntry(e); }}
                    >
                      <span className="fx-name" role="gridcell">
                        <span aria-hidden="true">{e.isDir ? '📁' : '📄'}</span>
                        <span className="n">{e.name}</span>
                      </span>
                      <span className="fx-meta">
                        {guardBadge(g)}
                        {e.isDir ? (
                          <Badge tone="neutral">{t('files.folder')}</Badge>
                        ) : (
                          <span className="muted">{formatSize(e.sizeBytes)}</span>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* tray: files marked with Space */}
            {selectedList.length > 0 && (
              <div className="fx-tray" role="group" aria-label={L('selected')}>
                <strong>{L('selected')}: {selectedList.length}</strong>
                <span className="muted fx-tray-names">
                  {selectedList.map((e) => e.name).join(', ')}
                </span>
                <Button small variant="ghost" onClick={() => setSelectedPaths(new Set())}>
                  {L('clearSel')}
                </Button>
              </div>
            )}

            <div className="fx-keys muted" aria-hidden="true">{L('keysHint')}</div>
          </div>

          {/* ── the inspector: preview / edit of the selected real file ── */}
          <div className="fx-col-plane">
            <h2 className="fx-plane-title">{preview ? preview.name : L('preview')}</h2>
            {preview ? (
              <PreviewPlane
                key={preview.path}
                entry={preview}
                onGuard={reportGuard}
                onEdit={setEditing}
              />
            ) : (
              <EmptyState glyph="▤" title={L('planePick')} hint={L('planePickHint')} />
            )}
          </div>
        </div>
      </section>

      {/* ── telemetry strip — counts from the real listing ─────────────────── */}
      <section className="surface soft fstats-wrap rise" aria-label={t('nav.files')}>
        <div className="fstats">
          {statCells.map((c) => (
            <div key={c.label} className={`fstat${c.tone ? ` fs-${c.tone}` : ''}`}>
              <b className="num">{c.v}</b>
              <span className="micro">{c.label}</span>
            </div>
          ))}
        </div>
      </section>

      {editing && <FileEditor entry={editing} onClose={() => setEditing(null)} />}

      <style>{`
        .v-files .bench-bar .crumb-seg { font: inherit; font-family: var(--f-mono);
          color: var(--ink-muted); background: none; border: 0; padding: 0 3px; cursor: pointer; border-radius: 5px; }
        .v-files .bench-bar .crumb-seg:hover { color: var(--cyan-soft); }
        .v-files .bench-bar .crumb-seg:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--cyan); }
        .v-files .fchips .chip .fx-chip-n { font-size: 11px; opacity: .75; padding-left: 2px; }
        .v-files .fx-actions { display: flex; gap: 6px; align-items: center; }
        .v-files .fx-actions .chip { width: 34px; justify-content: center; padding: 0; }
        .v-files .fx-count { font-size: 12px; color: var(--ink-muted); margin: 4px 2px var(--s4); }
        .v-files .fx-bench-body { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1.05fr);
          gap: var(--s5); align-items: start; }
        .v-files .fx-col-list, .v-files .fx-col-plane { min-width: 0; }
        .v-files .fx-col-plane { border-left: 1px solid rgb(var(--line-rgb)/.6); padding-left: var(--s5); }
        .v-files .fx-plane-title { font-size: var(--t-h2); margin: 0 0 var(--s4); }
        @media (max-width: 820px) {
          .v-files .fx-bench-body { grid-template-columns: 1fr; }
          .v-files .fx-col-plane { border-left: 0; padding-left: 0;
            border-top: 1px solid rgb(var(--line-rgb)/.6); padding-top: var(--s5); }
        }
        .fx-chip-n { font-variant-numeric: tabular-nums; opacity: 0.8; }
        .fx-grid { display: flex; flex-direction: column; gap: 2px; max-height: 52vh; overflow-y: auto;
          outline: none; border-radius: var(--menq-radius-md); }
        .fx-grid:focus-visible { box-shadow: 0 0 0 2px var(--menq-color-focus); }
        .fx-row { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3);
          padding: 8px 10px; border-radius: var(--menq-radius-md); cursor: pointer;
          border: 1px solid transparent; transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
        .fx-row:hover { background: var(--menq-color-hover); }
        .fx-row--cursor { background: var(--menq-color-hover); border-color: var(--brops-border); }
        .fx-row--selected { background: var(--menq-color-selected); }
        .fx-row--preview { border-color: var(--brops-accent); }
        .fx-name { display: flex; align-items: center; gap: var(--menq-space-2); min-width: 0; }
        .fx-name .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .fx-meta { display: flex; align-items: center; gap: var(--menq-space-2); flex: none; }
        .fx-tray { display: flex; align-items: center; gap: var(--menq-space-3); flex-wrap: wrap;
          margin-top: var(--menq-space-3); padding-top: var(--menq-space-3);
          border-top: 1px solid var(--brops-border); font-size: 12px; }
        .fx-tray-names { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; flex: 1; min-width: 0; }
        .fx-keys { font-size: 11px; margin-top: var(--menq-space-2); }
        .fx-preview-body { max-height: 52vh; overflow: auto; background: var(--brops-bg);
          border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); padding: var(--menq-space-4); }
        .fx-pre { margin: 0; white-space: pre-wrap; word-break: break-word;
          font-family: var(--menq-font-mono); font-size: 12.5px; line-height: 1.5; color: var(--brops-text); }
        .fx-blocked { text-align: center; padding: var(--menq-space-6) var(--menq-space-4); color: var(--brops-muted); }
        .fx-blocked-glyph { font-size: 28px; }
        .fx-fade { animation: fx-fade var(--menq-motion-med) ease-out; }
        @keyframes fx-fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
        @media (prefers-reduced-motion: reduce) {
          .fx-fade { animation: none; }
          .fx-row, .fx-chip { transition: none; }
        }
      `}</style>
    </div>
  );
}
