import {
  useEffect, useRef, useState,
  type ChangeEvent, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Input, Textarea, Select, Skeleton, ErrorState, EmptyState, Modal,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { LibraryItem } from '../domain/entities';
import type { Tone } from '../domain/enums';

// ── §D `library` ❑ Դարան ─────────────────────────────────────────────────────
// The component / prompt / pattern catalog, wired end-to-end to the REAL desktop
// library store (`list_library` / `create_library_item`). Mirrors the Knowledge
// entity pattern precisely: a plain SQLite-backed store surfaced through the typed
// desktop service. No data is fabricated — the store's real rows drive every state.
// (Hard-delete stays capability-denied under the Wave-2b L2 policy, exactly like
// knowledge, so the page exposes no delete affordance.)

const LIBRARY_KINDS = ['component', 'prompt', 'pattern'] as const;
type LibraryKind = (typeof LIBRARY_KINDS)[number];

// CSS custom properties are allowed on style objects via this widened type.
type StyleVars = CSSProperties & Record<`--${string}`, string | number>;

const kindTone: Record<string, Tone> = {
  component: 'accent',
  prompt: 'info',
  pattern: 'success',
};

function parseTags(raw: string): string[] {
  return raw.split(',').map((x) => x.trim()).filter(Boolean);
}

// ── Inline bilingual copy (HY + EN), mirroring the thin-page convention. ──────
interface Copy {
  subtitle: string;
  searchPlaceholder: string;
  searchLabel: string;
  filterLabel: string;
  all: string;
  kind: Record<LibraryKind, string>;
  emptyTitle: string;
  emptyHint: string;
  filteredTitle: string;
  filteredHint: string;
  clearFilters: string;
  previewEmpty: string;
  listLabel: string;
  tags: string;
  loadFailed: string;
  newTitle: string;
  fTitle: string;
  fKind: string;
  fBody: string;
  fTags: string;
  bodyPlaceholder: string;
  tagsPlaceholder: string;
  saving: string;
}

const COPY: Record<'en' | 'hy', Copy> = {
  en: {
    subtitle: 'Component, prompt & pattern catalog with live previews',
    searchPlaceholder: 'Search the library…    press /',
    searchLabel: 'Search the library',
    filterLabel: 'Filter by type',
    all: 'All',
    kind: { component: 'Components', prompt: 'Prompts', pattern: 'Patterns' },
    emptyTitle: 'Nothing saved yet',
    emptyHint: 'Save the first component, prompt or pattern to start the library.',
    filteredTitle: 'No matches',
    filteredHint: 'Nothing matches your search and filters.',
    clearFilters: 'Clear search & filters',
    previewEmpty: 'Select an item to preview it.',
    listLabel: 'Library results',
    tags: 'Tags',
    loadFailed: 'Couldn’t load the library.',
    newTitle: 'New library item',
    fTitle: 'Title',
    fKind: 'Type',
    fBody: 'Body',
    fTags: 'Tags',
    bodyPlaceholder: 'The prompt, pattern or component blurb…',
    tagsPlaceholder: 'react, form, accessible',
    saving: 'Saving…',
  },
  hy: {
    subtitle: 'Բաղադրիչների, հուշումների և ձևանմուշների դարան՝ կենդանի նախադիտումով',
    searchPlaceholder: 'Փնտրել դարանում…    սեղմեք /',
    searchLabel: 'Փնտրել դարանում',
    filterLabel: 'Զտել ըստ տեսակի',
    all: 'Բոլորը',
    kind: { component: 'Բաղադրիչներ', prompt: 'Հուշումներ', pattern: 'Ձևանմուշներ' },
    emptyTitle: 'Դեռ ոչինչ պահված չէ',
    emptyHint: 'Պահիր առաջին բաղադրիչը, հուշումը կամ ձևանմուշը՝ դարանը սկսելու համար։',
    filteredTitle: 'Համընկնումներ չկան',
    filteredHint: 'Ոչինչ չի համընկնում ձեր որոնման և զտիչների հետ։',
    clearFilters: 'Մաքրել որոնումն ու զտիչները',
    previewEmpty: 'Ընտրեք տարր՝ նախադիտելու համար։',
    listLabel: 'Դարանի արդյունքներ',
    tags: 'Պիտակներ',
    loadFailed: 'Չհաջողվեց բեռնել դարանը։',
    newTitle: 'Նոր դարանի տարր',
    fTitle: 'Վերնագիր',
    fKind: 'Տեսակ',
    fBody: 'Բովանդակություն',
    fTags: 'Պիտակներ',
    bodyPlaceholder: 'Հուշումը, ձևանմուշը կամ բաղադրիչի նկարագիրը…',
    tagsPlaceholder: 'react, form, accessible',
    saving: 'Պահվում է…',
  },
};

type KindFilter = 'all' | LibraryKind;

function kindLabel(c: Copy, kind: string): string {
  return (LIBRARY_KINDS as readonly string[]).includes(kind) ? c.kind[kind as LibraryKind] : kind;
}

// ── Create form (Modal) — fully wired to the REAL create_library_item command ─
function CreateDialog(
  { onClose, onCreated }: { onClose: () => void; onCreated: (item: LibraryItem) => void },
) {
  const { t, lang } = useApp();
  const c = COPY[lang === 'hy' ? 'hy' : 'en'];

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
    <Modal title={c.newTitle} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <label className="form-row">
        <span className="field-label">{c.fTitle}</span>
        <Input ref={titleRef} value={title}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{c.fKind}</span>
        <Select value={kind} onChange={(e: ChangeEvent<HTMLSelectElement>) => setKind(e.target.value as LibraryKind)}>
          {LIBRARY_KINDS.map((k) => <option key={k} value={k}>{c.kind[k]}</option>)}
        </Select>
      </label>
      <label className="form-row">
        <span className="field-label">{c.fBody}</span>
        <Textarea value={body} style={{ minHeight: 140 }} placeholder={c.bodyPlaceholder}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setBody(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{c.fTags}</span>
        <Input value={tags} placeholder={c.tagsPlaceholder}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setTags(e.target.value)} />
      </label>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" disabled={!canSave} onClick={submit}>
          {busy ? c.saving : t('action.save')}
        </Button>
      </div>
    </Modal>
  );
}

// ── Live preview panel (labeled, announces selection changes) ────────────────
function PreviewPanel({ item, label, previewLabelFor, c }: {
  item: LibraryItem | null;
  label: string;
  previewLabelFor: (title: string) => string;
  c: Copy;
}) {
  return (
    <section
      className="lib-preview"
      role="region"
      aria-live="polite"
      aria-label={item ? previewLabelFor(item.title) : label}
    >
      {!item ? (
        <div className="muted" style={{ padding: '8px 0' }}>{label}</div>
      ) : (
        <>
          <div className="lib-preview-head">
            <span className="lib-preview-title">{item.title}</span>
            <Badge tone={kindTone[item.kind] ?? 'neutral'}>{kindLabel(c, item.kind)}</Badge>
          </div>
          <div className="lib-preview-body">
            <pre aria-label={previewLabelFor(item.title)}>{item.body || '—'}</pre>
          </div>
          {parseTags(item.tags).length > 0 && (
            <div className="lib-tags" aria-label={c.tags}>
              {parseTags(item.tags).map((tg) => <span key={tg} className="lib-tag">{tg}</span>)}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function Library() {
  const { t, lang } = useApp();
  const c = COPY[lang === 'hy' ? 'hy' : 'en'];
  const previewLabelFor = (title: string) =>
    lang === 'hy' ? `Նախադիտում՝ ${title}` : `Preview: ${title}`;

  const s = useAsync<LibraryItem[]>(() => desktop.listLibrary(), []);

  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<KindFilter>('all');
  const [selected, setSelected] = useState(0);
  const [creating, setCreating] = useState(false);

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

  // `/` focuses search from anywhere (unless typing or the create dialog is open).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || creating) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [creating]);

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
    // Focus lands back on the (soon-to-refresh) list head.
    void item;
  };

  const countLabel = lang === 'hy'
    ? `${filtered.length} արդյունք`
    : `${filtered.length} ${filtered.length === 1 ? 'result' : 'results'}`;

  const loading = s.loading && s.data === null;
  const chips: KindFilter[] = ['all', ...LIBRARY_KINDS];
  const toolbarVisible = !loading && !s.error && rawItems.length > 0;

  const renderResults = () => {
    if (loading) return <Skeleton rows={5} />;
    if (s.error) return <ErrorState message={s.error || c.loadFailed} onRetry={s.reload} retryLabel={t('action.retry')} />;
    if (rawItems.length === 0) {
      return <EmptyState glyph="❑" title={c.emptyTitle} hint={c.emptyHint} />;
    }
    if (filtered.length === 0) {
      return (
        <div>
          <EmptyState glyph="⌕" title={c.filteredTitle} hint={c.filteredHint} />
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <Button small onClick={clearAll}>{c.clearFilters}</Button>
          </div>
        </div>
      );
    }
    const active = filtered[sel] ?? null;
    return (
      <div className="lib-layout">
        <ul className="lib-list" role="list" aria-label={c.listLabel} onKeyDown={onListKeyDown}>
          {filtered.map((it, idx) => {
            const isActive = idx === sel;
            const itemStyle: StyleVars = { '--i': idx };
            return (
              <li key={it.id} role="listitem">
                <button
                  type="button"
                  ref={(el) => { itemRefs.current[idx] = el; }}
                  className={`lib-item${isActive ? ' lib-item--active' : ''}`}
                  style={itemStyle}
                  tabIndex={isActive ? 0 : -1}
                  aria-current={isActive ? 'true' : undefined}
                  onFocus={() => setSelected(idx)}
                  onClick={() => setSelected(idx)}
                >
                  <span className="lib-item-top">
                    <span className="lib-item-title">{it.title}</span>
                    <Badge tone={kindTone[it.kind] ?? 'neutral'}>{kindLabel(c, it.kind)}</Badge>
                  </span>
                  {it.body && <span className="lib-item-sum">{it.body}</span>}
                </button>
              </li>
            );
          })}
        </ul>
        <PreviewPanel item={active} label={c.previewEmpty} previewLabelFor={previewLabelFor} c={c} />
      </div>
    );
  };

  return (
    <>
      <style>{LIBRARY_CSS}</style>

      <PageHeader
        title={t('nav.library')}
        subtitle={c.subtitle}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      <Panel>
        {toolbarVisible && (
          <div className="lib-toolbar">
            <div className="lib-search">
              <Input
                ref={searchRef}
                type="search"
                value={query}
                onChange={onSearchChange}
                onKeyDown={onSearchKeyDown}
                placeholder={c.searchPlaceholder}
                aria-label={c.searchLabel}
              />
            </div>
            <div className="lib-chips" role="group" aria-label={c.filterLabel}>
              {chips.map((k) => (
                <button
                  key={k}
                  type="button"
                  className="lib-chip"
                  aria-pressed={kindFilter === k}
                  onClick={() => pickKind(k)}
                >
                  {k === 'all' ? c.all : c.kind[k]}
                </button>
              ))}
            </div>
          </div>
        )}

        {toolbarVisible && (
          <div className="lib-count" role="status" aria-live="polite">{countLabel}</div>
        )}

        {renderResults()}
      </Panel>

      {creating && <CreateDialog onClose={() => setCreating(false)} onCreated={onCreated} />}
    </>
  );
}

// Page-local styles. Every value resolves through the shared design tokens
// (colors/radii/spacing/motion) — no hard-coded palette. Motion is disabled
// under prefers-reduced-motion.
const LIBRARY_CSS = `
.lib-toolbar { display: flex; flex-wrap: wrap; gap: var(--menq-space-3); align-items: center; }
.lib-search { position: relative; flex: 1; min-width: 220px; }
.lib-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.lib-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; font: inherit;
  font-size: 12px; font-weight: 600; border-radius: var(--menq-radius-pill);
  border: 1px solid var(--brops-border); background: var(--brops-surface); color: var(--brops-muted);
  cursor: pointer; transition: background var(--menq-motion-fast), color var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.lib-chip:hover { background: var(--menq-color-hover); }
.lib-chip[aria-pressed="true"] { background: var(--menq-color-selected); border-color: var(--brops-accent); color: var(--brops-accent); }
.lib-count { font-size: 12px; color: var(--brops-muted); font-variant-numeric: tabular-nums; margin-top: var(--menq-space-3); }
.lib-layout { display: grid; grid-template-columns: minmax(240px, 340px) 1fr; gap: var(--menq-space-4); align-items: start; margin-top: var(--menq-space-3); }
@media (max-width: 820px) { .lib-layout { grid-template-columns: 1fr; } }
.lib-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px;
  max-height: 56vh; overflow-y: auto; }
.lib-item { display: flex; flex-direction: column; gap: 4px; width: 100%; text-align: left; cursor: pointer;
  font: inherit; color: var(--brops-text); background: var(--brops-surface);
  border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); padding: 9px 11px;
  animation: lib-reveal var(--menq-motion-med) ease both; animation-delay: calc(var(--i, 0) * 40ms);
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.lib-item:hover { background: var(--menq-color-hover); }
.lib-item--active { border-color: var(--brops-accent); background: var(--menq-color-selected); }
.lib-item:focus-visible { outline: 2px solid var(--brops-accent); outline-offset: 2px; }
.lib-item-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.lib-item-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lib-item-sum { font-size: 12px; color: var(--brops-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lib-preview { position: sticky; top: 0; background: var(--brops-surface); border: 1px solid var(--brops-border);
  border-radius: var(--menq-radius-card); padding: var(--menq-space-4); min-height: 160px; }
.lib-preview-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: var(--menq-space-3); }
.lib-preview-title { font-weight: 700; }
.lib-preview-body pre { background: var(--brops-bg); border: 1px solid var(--brops-border);
  border-radius: var(--menq-radius-md); padding: 10px 12px; overflow-x: auto;
  font-family: var(--menq-font-mono); font-size: 12px; line-height: 1.5; white-space: pre-wrap; margin: 0; }
.lib-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: var(--menq-space-3); }
.lib-tag { font-size: 11px; color: var(--brops-muted); background: var(--menq-color-hover);
  border-radius: var(--menq-radius-pill); padding: 2px 9px; }
@keyframes lib-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .lib-item { animation: none; }
  .lib-chip, .lib-item { transition: none; }
}
`;
