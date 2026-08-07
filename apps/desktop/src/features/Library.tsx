import {
  useEffect, useRef, useState,
  type ChangeEvent, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  Button, Input, Textarea, Select, Skeleton, ErrorState, EmptyState, Modal, ConfirmDialog,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { LibraryItem } from '../domain/entities';
import type { Lang } from '../domain/enums';
import { STR } from './Library.strings';

// ── §D `library` ❑ Դարան — reskinned to the brops-aios "Դարան / Archive" ──────
// The component / prompt / pattern catalog, wired end-to-end to the REAL desktop
// library store (`list_library` / `create_library_item` / `delete_library_item`).
// The mockup's SKILL-shelf metaphor (proof-maturity heights, proven/drafted
// tiers, a 95% success stat and a telemetry sparkline) has NO backing store, so
// none of it is fabricated: the archive index, the totals capsules and every
// count are derived purely from the real rows the store returns.

const LIBRARY_KINDS = ['component', 'prompt', 'pattern'] as const;
type LibraryKind = (typeof LIBRARY_KINDS)[number];

// CSS custom properties are allowed on style objects via this widened type.
type StyleVars = CSSProperties & Record<`--${string}`, string | number>;

function parseTags(raw: string): string[] {
  return raw.split(',').map((x) => x.trim()).filter(Boolean);
}

// ── Trilingual copy lives in Library.strings.ts. `L` resolves a key against the
// active language (falling back to English), so switching language re-renders
// the whole page in one language. ────────────────────────────────────────────
type StrKey = keyof typeof STR;
type Localize = (k: StrKey) => string;

const makeL = (lang: Lang): Localize => (k) => STR[k][lang] ?? STR[k].en;

// Per-kind label keys, so `L(KIND_KEY[kind])` yields the localized noun.
const KIND_KEY: Record<LibraryKind, StrKey> = {
  component: 'kindComponent',
  prompt: 'kindPrompt',
  pattern: 'kindPattern',
};

type KindFilter = 'all' | LibraryKind;

function kindLabel(L: Localize, kind: string): string {
  return (LIBRARY_KINDS as readonly string[]).includes(kind)
    ? L(KIND_KEY[kind as LibraryKind]) : kind;
}

// ── Create form (Modal) — fully wired to the REAL create_library_item command ─
function CreateDialog(
  { onClose, onCreated }: { onClose: () => void; onCreated: (item: LibraryItem) => void },
) {
  const { t, lang } = useApp();
  const L = makeL(lang);

  const [title, setTitle] = useState('');
  const [kind, setKind] = useState<LibraryKind>('component');
  const [body, setBody] = useState('');
  const [tags, setTags] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const titleRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => { titleRef.current?.focus(); }, []);

  const canSave = title.trim().length > 0 && !busy;

  const submit = () => {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    desktop
      .createLibraryItem({ title: title.trim(), kind, body: body.trim(), tags: tags.trim() })
      .then((created) => onCreated(created))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={L('newTitle')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <label className="form-row">
        <span className="field-label">{L('fTitle')}</span>
        <Input ref={titleRef} value={title}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{L('fKind')}</span>
        <Select value={kind} onChange={(e: ChangeEvent<HTMLSelectElement>) => setKind(e.target.value as LibraryKind)}>
          {LIBRARY_KINDS.map((k) => <option key={k} value={k}>{L(KIND_KEY[k])}</option>)}
        </Select>
      </label>
      <label className="form-row">
        <span className="field-label">{L('fBody')}</span>
        <Textarea value={body} style={{ minHeight: 140 }} placeholder={L('bodyPlaceholder')}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setBody(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{L('fTags')}</span>
        <Input value={tags} placeholder={L('tagsPlaceholder')}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setTags(e.target.value)} />
      </label>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" disabled={!canSave} onClick={submit}>
          {busy ? L('saving') : t('action.save')}
        </Button>
      </div>
    </Modal>
  );
}

// ── Live preview panel — the opened "codex" (labeled, announces selection) ────
function PreviewPanel({ item, label, previewLabelFor, L }: {
  item: LibraryItem | null;
  label: string;
  previewLabelFor: (title: string) => string;
  L: Localize;
}) {
  return (
    <section
      className="lib-codex surface soft"
      role="region"
      aria-live="polite"
      aria-label={item ? previewLabelFor(item.title) : label}
    >
      {!item ? (
        <div className="lib-codex-empty micro">{label}</div>
      ) : (
        <>
          <div className="lib-codex-head">
            <span className="eyebrow">{kindLabel(L, item.kind)}</span>
            <h3 className="lib-codex-title">{item.title}</h3>
          </div>
          <div className="lib-codex-body">
            <pre aria-label={previewLabelFor(item.title)}>{item.body || '—'}</pre>
          </div>
          {parseTags(item.tags).length > 0 && (
            <div className="lib-tags" aria-label={L('tags')}>
              {parseTags(item.tags).map((tg) => <span key={tg} className="tag">{tg}</span>)}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function Library() {
  const { t, lang } = useApp();
  const L = makeL(lang);
  const previewLabelFor = (title: string) => `${L('previewPrefix')}${title}`;

  const s = useAsync<LibraryItem[]>(() => desktop.listLibrary(), []);

  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<KindFilter>('all');
  const [selected, setSelected] = useState(0);
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<LibraryItem | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  // The backend's own reason for REFUSING a delete. There was no `.catch` here at all,
  // so a denied `delete_library_item` closed the dialog and reloaded the same row back
  // with nothing said. Now the refusal is stated and stays until dismissed.
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const searchRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const rawItems: LibraryItem[] = s.data ?? [];

  const q = query.trim().toLowerCase();
  const filtered = rawItems.filter((it) => {
    if (kindFilter !== 'all' && it.kind !== kindFilter) return false;
    if (!q) return true;
    return (
      it.title.toLowerCase().includes(q) ||
      it.body.toLowerCase().includes(q) ||
      parseTags(it.tags).some((tg) => tg.toLowerCase().includes(q))
    );
  });

  const sel = filtered.length ? Math.min(selected, filtered.length - 1) : 0;

  // `/` focuses search from anywhere (unless typing or a dialog is open).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || creating || pendingDelete) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [creating, pendingDelete]);

  const moveSelection = (to: number) => {
    const n = filtered.length;
    if (!n) return;
    const next = ((to % n) + n) % n;
    setSelected(next);
    requestAnimationFrame(() => itemRefs.current[next]?.focus());
  };

  const onListKeyDown = (e: ReactKeyboardEvent<HTMLUListElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveSelection(sel + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveSelection(sel - 1); }
    else if (e.key === 'Home') { e.preventDefault(); moveSelection(0); }
    else if (e.key === 'End') { e.preventDefault(); moveSelection(filtered.length - 1); }
  };

  const onSearchChange = (e: ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
    setSelected(0);
  };
  const onSearchKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape' && query) {
      e.preventDefault();
      setQuery('');
    } else if (e.key === 'ArrowDown' && filtered.length) {
      e.preventDefault();
      moveSelection(0);
    }
  };

  const pickKind = (k: KindFilter) => { setKindFilter(k); setSelected(0); };
  const clearAll = () => { setQuery(''); setKindFilter('all'); setSelected(0); };

  const onCreated = (item: LibraryItem) => {
    setCreating(false);
    setQuery('');
    setKindFilter('all');
    setSelected(0);
    s.reload();
    void item;
  };

  // ── REAL hard-delete (delete_library_item), gated behind ConfirmDialog. ──
  const confirmDelete = () => {
    if (!pendingDelete || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError(null);
    desktop
      .deleteLibraryItem(pendingDelete.id)
      .then(() => { setSelected(0); })
      .catch((e: unknown) => {
        setDeleteError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        setPendingDelete(null);
        setDeleteBusy(false);
        // Re-read either way: on success the row is gone, on refusal it provably is not.
        s.reload();
      });
  };

  // Totals + per-kind breakdown — derived only from the real rows.
  const total = rawItems.length;
  const kindCounts: Record<LibraryKind, number> = {
    component: 0, prompt: 0, pattern: 0,
  };
  rawItems.forEach((it) => {
    if ((LIBRARY_KINDS as readonly string[]).includes(it.kind)) kindCounts[it.kind as LibraryKind] += 1;
  });

  // Localized "N results" — English singular/plural, Armenian invariant,
  // Russian three-way plural (1 / 2–4 / 5+).
  const resultNoun = (n: number): string => {
    if (lang === 'ru') {
      const m10 = n % 10;
      const m100 = n % 100;
      if (m10 === 1 && m100 !== 11) return L('resultOne');
      if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return L('resultFew');
      return L('resultMany');
    }
    if (lang === 'en') return n === 1 ? L('resultOne') : L('resultFew');
    return L('resultOne');
  };
  const countLabel = `${filtered.length} ${resultNoun(filtered.length)}`;

  const loading = s.loading && s.data === null;
  const chips: KindFilter[] = ['all', ...LIBRARY_KINDS];
  const toolbarVisible = !loading && !s.error && rawItems.length > 0;

  const renderResults = () => {
    if (loading) return <Skeleton rows={5} />;
    if (s.error) return <ErrorState message={s.error || L('loadFailed')} onRetry={s.reload} retryLabel={t('action.retry')} />;
    if (rawItems.length === 0) {
      return <EmptyState glyph="❑" title={L('emptyTitle')} hint={L('emptyHint')} />;
    }
    if (filtered.length === 0) {
      return (
        <div>
          <EmptyState glyph="⌕" title={L('filteredTitle')} hint={L('filteredHint')} />
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <Button small onClick={clearAll}>{L('clearFilters')}</Button>
          </div>
        </div>
      );
    }
    const active = filtered[sel] ?? null;
    return (
      <div className="lib-layout">
        <ul className="lib-list" role="list" aria-label={L('listLabel')} onKeyDown={onListKeyDown}>
          {filtered.map((it, idx) => {
            const isActive = idx === sel;
            const itemStyle: StyleVars = { '--i': idx };
            const deleteName = `${t('action.delete')}: ${it.title}`;
            return (
              <li key={it.id} role="listitem" className="lib-row" style={itemStyle}>
                <button
                  type="button"
                  ref={(el) => { itemRefs.current[idx] = el; }}
                  className={`lib-item${isActive ? ' lib-item--active' : ''}`}
                  tabIndex={isActive ? 0 : -1}
                  aria-current={isActive ? 'true' : undefined}
                  onFocus={() => setSelected(idx)}
                  onClick={() => setSelected(idx)}
                >
                  <span className="lib-item-top">
                    <span className="lib-item-title">{it.title}</span>
                    <span className={`tag tag--${it.kind}`}>{kindLabel(L, it.kind)}</span>
                  </span>
                  {it.body && <span className="lib-item-sum">{it.body}</span>}
                </button>
                <button
                  type="button"
                  className="lib-del"
                  aria-label={deleteName}
                  title={deleteName}
                  onClick={() => setPendingDelete(it)}
                >
                  <span aria-hidden="true">✕</span>
                </button>
              </li>
            );
          })}
        </ul>
        <PreviewPanel item={active} label={L('previewEmpty')} previewLabelFor={previewLabelFor} L={L} />
      </div>
    );
  };

  return (
    <div className="v-library">
      <style>{LIBRARY_CSS}</style>

      {/* ── HEADER ─────────────────────────────────────────────────────────── */}
      <header className="pageHead reveal">
        <div>
          <span className="eyebrow">{L('eyebrow')}</span>
          <h1>{t('nav.library')}</h1>
          <p className="sub">{L('subtitle')}</p>
        </div>
        <div className="right">
          {toolbarVisible && <span className="pill info">{L('archiveRead')}</span>}
          <Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>
          {/* Posture from the REAL read: alert on failure, idle otherwise. `live`
              would assert a running process this page does not have. */}
          <Mark state={s.error ? 'alert' : 'idle'} size={30} />
        </div>
      </header>

      {/* A REFUSED delete, stated plainly and left on screen until dismissed. */}
      {deleteError && (
        <div className="lib-delete-error" role="alert">
          <b>{L('deleteRefusedTitle')}</b>
          <span>{L('deleteRefusedBody')}</span>
          <span className="mono lib-delete-reason">{deleteError}</span>
          <Button small variant="ghost" onClick={() => setDeleteError(null)}>{t('action.close')}</Button>
        </div>
      )}

      {/* ── HERO · the archive surface ─────────────────────────────────────── */}
      <section className="lib-archive surface soft lg hud reveal" style={{ '--i': 1 } as StyleVars}>
        <span className="bracket tl" aria-hidden="true" />
        <span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" />
        <span className="bracket br" aria-hidden="true" />

        {toolbarVisible && (
          <div className="lib-totals" role="group" aria-label={L('totalsLabel')}>
            <span className="capsule">
              <b className="num">{total}</b><span>{L('total')}</span>
            </span>
            {LIBRARY_KINDS.map((k) => (
              <span key={k} className="capsule">
                <b className="num">{kindCounts[k]}</b><span>{L(KIND_KEY[k])}</span>
              </span>
            ))}
          </div>
        )}

        {toolbarVisible && (
          <div className="sec-head">
            <h2>{L('indexTitle')}</h2>
            <div className="lib-count" role="status" aria-live="polite">{countLabel}</div>
          </div>
        )}

        {toolbarVisible && (
          <div className="lib-toolbar">
            <div className="lib-search">
              <Input
                ref={searchRef}
                type="search"
                value={query}
                onChange={onSearchChange}
                onKeyDown={onSearchKeyDown}
                placeholder={L('searchPlaceholder')}
                aria-label={L('searchLabel')}
              />
            </div>
            <div className="lib-chips" role="group" aria-label={L('filterLabel')}>
              {chips.map((k) => (
                <button
                  key={k}
                  type="button"
                  className={`chip${kindFilter === k ? ' on' : ''}`}
                  aria-pressed={kindFilter === k}
                  onClick={() => pickKind(k)}
                >
                  {k === 'all' ? L('all') : L(KIND_KEY[k])}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* A plain divider. The `live` modifier animates a travelling pulse, which reads
            as a running stream; this page has one read and no stream, so the claim is
            dropped rather than faked. */}
        <div className="wire" aria-hidden="true" />

        {renderResults()}
      </section>

      {creating && <CreateDialog onClose={() => setCreating(false)} onCreated={onCreated} />}
      {pendingDelete && (
        <ConfirmDialog
          title={L('deleteTitle')}
          message={`${pendingDelete.title} — ${L('deleteConfirm')}`}
          confirmLabel={deleteBusy ? L('deleting') : t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={confirmDelete}
          onCancel={() => { if (!deleteBusy) setPendingDelete(null); }}
        />
      )}
    </div>
  );
}

// Page-local styles, scoped to `.v-library`. Every value resolves through the
// shared brops-aios tokens (colors/radii/spacing/motion) — no hard-coded
// palette. Motion is disabled under prefers-reduced-motion.
const LIBRARY_CSS = `
.v-library .lib-delete-error { display: flex; flex-direction: column; align-items: flex-start; gap: 6px;
  margin-bottom: var(--s4); padding: 10px 12px;
  border: 1px solid rgb(var(--danger-rgb)/.4); border-radius: var(--r);
  background: rgb(var(--danger-rgb)/.08); font-size: var(--t-small); }
.v-library .lib-delete-error b { color: var(--danger); }
.v-library .lib-delete-reason { color: var(--ink-muted); font-size: 12px; word-break: break-word; }

.v-library .lib-archive { padding: var(--s6); }
.v-library .lib-totals { display: flex; flex-wrap: wrap; gap: var(--s3); margin-bottom: var(--s5); }
.v-library .lib-totals .capsule b { color: var(--ink); }

.v-library .sec-head { margin-bottom: var(--s3); }
.v-library .lib-count { font-family: var(--f-mono); font-size: var(--t-small); color: var(--ink-muted);
  font-variant-numeric: tabular-nums; }

.v-library .lib-toolbar { display: flex; flex-wrap: wrap; gap: var(--s3); align-items: center; }
.v-library .lib-search { position: relative; flex: 1; min-width: 220px; }
.v-library .lib-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.v-library .lib-chips .chip { cursor: pointer; }
.v-library .lib-chips .chip.on { color: var(--cyan-soft); border-color: rgb(var(--cyan-rgb)/.45);
  background: rgb(var(--cyan-rgb)/.09); box-shadow: 0 0 18px rgb(var(--cyan-rgb)/.14); }

.v-library .lib-layout { display: grid; grid-template-columns: minmax(240px, 360px) 1fr;
  gap: var(--s5); align-items: start; }
@media (max-width: 860px) { .v-library .lib-layout { grid-template-columns: 1fr; } }

.v-library .lib-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column;
  gap: 8px; max-height: 58vh; overflow-y: auto; }
.v-library .lib-row { display: grid; grid-template-columns: 1fr auto; align-items: stretch; gap: 6px;
  animation: lib-reveal var(--slow) var(--enter) both; animation-delay: calc(var(--i, 0) * 32ms); }

.v-library .lib-item { display: flex; flex-direction: column; gap: 5px; width: 100%; text-align: left;
  cursor: pointer; font: inherit; color: var(--ink); background: rgb(var(--raised-rgb)/.55);
  border: 1px solid var(--line); border-radius: var(--r-lg); padding: 11px 13px;
  transition: background var(--fast), border-color var(--fast), box-shadow var(--fast); }
.v-library .lib-item:hover { background: rgb(var(--raised-rgb)/.85); border-color: rgb(var(--cyan-rgb)/.28); }
.v-library .lib-item--active { border-color: rgb(var(--cyan-rgb)/.5); background: rgb(var(--cyan-rgb)/.08);
  box-shadow: 0 0 26px -10px rgb(var(--cyan-rgb)/.5); }
.v-library .lib-item:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
.v-library .lib-item-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.v-library .lib-item-title { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.v-library .lib-item-sum { font-size: var(--t-small); color: var(--ink-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.v-library .tag--component { color: var(--cyan-soft); border-color: rgb(var(--cyan-rgb)/.22);
  background: rgb(var(--cyan-rgb)/.08); }
.v-library .tag--prompt { color: var(--azure-soft); border-color: rgb(var(--azure-soft-rgb)/.22);
  background: rgb(var(--azure-rgb)/.08); }
.v-library .tag--pattern { color: var(--mint); border-color: rgb(var(--mint-rgb)/.22);
  background: rgb(var(--mint-rgb)/.08); }

.v-library .lib-del { display: inline-flex; align-items: center; justify-content: center; width: 34px;
  flex: none; font: inherit; color: var(--ink-muted); background: rgb(var(--raised-rgb)/.4);
  border: 1px solid var(--line); border-radius: var(--r-lg); cursor: pointer;
  transition: color var(--fast), border-color var(--fast), background var(--fast); }
.v-library .lib-del:hover { color: var(--danger); border-color: rgb(var(--danger-rgb)/.4);
  background: rgb(var(--danger-rgb)/.08); }
.v-library .lib-del:focus-visible { outline: 2px solid var(--danger); outline-offset: 2px; }

.v-library .lib-codex { position: sticky; top: 0; padding: var(--s5); min-height: 180px; }
.v-library .lib-codex-empty { color: var(--ink-muted); padding: var(--s3) 0; }
.v-library .lib-codex-head { display: flex; flex-direction: column; gap: 6px; margin-bottom: var(--s4); }
.v-library .lib-codex-title { margin: 0; font-family: var(--f-display); font-weight: 800;
  font-size: var(--t-h2); letter-spacing: -.01em; }
.v-library .lib-codex-body pre { background: rgb(var(--bg-rgb)/.6); border: 1px solid var(--line);
  border-radius: var(--r); padding: 12px 14px; overflow-x: auto; font-family: var(--f-mono);
  font-size: var(--t-small); line-height: 1.55; white-space: pre-wrap; margin: 0; color: var(--ink); }
.v-library .lib-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: var(--s4); }

@keyframes lib-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .v-library .lib-row { animation: none; }
  .v-library .lib-item, .v-library .lib-del, .v-library .lib-chips .chip { transition: none; }
}
`;
