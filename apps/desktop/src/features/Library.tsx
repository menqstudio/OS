import {
  useEffect, useRef, useState,
  type ChangeEvent, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Input, Skeleton, ErrorState, EmptyState, Modal,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import type { Tone } from '../domain/enums';

// ── Domain shapes for the catalog ────────────────────────────────────────────
// Internal prop contract for a catalog entry (ROADMAP §"library": a
// component/prompt/pattern catalog). `source` records which of the two spec
// data sources the entry came from — the desktop library store (product) or the
// engine skill registry (read-only).
type LibraryKind = 'component' | 'prompt' | 'pattern';
type LibrarySourceTag = 'product' | 'registry';

interface LibraryItem {
  id: string;
  kind: LibraryKind;
  source: LibrarySourceTag;
  title: string;
  summary: string;
  /** Text shown in the live preview (a prompt/pattern body, or a component blurb). */
  preview: string;
  tags: string[];
}

// The store is either wired (`ready` + its items) or not yet backed by a command.
type LibrarySource =
  | { kind: 'unavailable' }
  | { kind: 'ready'; items: LibraryItem[] };

// Honest data boundary. The two data sources the spec names for this page — the
// desktop library store (product) and the engine skill registry (read) — have NO
// Tauri command on `desktop` yet (ROADMAP Phase 4 backend leg / `list_library`).
// We never fabricate catalog rows, so the store reports itself unavailable and
// the page renders its honest "not yet connected" state. The moment a real
// `list_library` command lands, replace the body with that call returning
// `{ kind: 'ready', items }` and every render path below lights up unchanged.
async function loadLibrarySource(): Promise<LibrarySource> {
  return { kind: 'unavailable' };
}

// CSS custom properties are allowed on style objects via this widened type.
type StyleVars = CSSProperties & Record<`--${string}`, string | number>;

const kindTone: Record<LibraryKind, Tone> = {
  component: 'accent',
  prompt: 'info',
  pattern: 'success',
};

// ── Inline bilingual copy (HY + EN), mirroring the thin-page convention. The
// shared i18n files are intentionally left untouched. ────────────────────────
interface Copy {
  subtitle: string;
  searchPlaceholder: string;
  searchLabel: string;
  filterLabel: string;
  all: string;
  kind: Record<LibraryKind, string>;
  source: Record<LibrarySourceTag, string>;
  emptyTitle: string;
  emptyHint: string;
  filteredTitle: string;
  filteredHint: string;
  clearFilters: string;
  unavailableTitle: string;
  unavailableHint: string;
  previewEmpty: string;
  listLabel: string;
  open: string;
  close: string;
  tags: string;
  loadFailed: string;
}

const COPY: Record<'en' | 'hy', Copy> = {
  en: {
    subtitle: 'Component, prompt & pattern catalog with live previews',
    searchPlaceholder: 'Search the library…    press /',
    searchLabel: 'Search the library',
    filterLabel: 'Filter by type',
    all: 'All',
    kind: { component: 'Components', prompt: 'Prompts', pattern: 'Patterns' },
    source: { product: 'Saved', registry: 'Skill registry' },
    emptyTitle: 'Nothing saved yet',
    emptyHint: 'Saved components, prompts and patterns will appear here once you add them.',
    filteredTitle: 'No matches',
    filteredHint: 'Nothing matches your search and filters.',
    clearFilters: 'Clear search & filters',
    unavailableTitle: 'Library isn’t connected yet',
    unavailableHint:
      'The desktop library store and the engine skill-registry read have no backend command yet (ROADMAP Phase 4). No placeholder data is shown — the catalog appears here once those commands land.',
    previewEmpty: 'Select an item to preview it.',
    listLabel: 'Library results',
    open: 'Open',
    close: 'Close',
    tags: 'Tags',
    loadFailed: 'Couldn’t load the library.',
  },
  hy: {
    subtitle: 'Բաղադրիչների, հուշումների և ձևանմուշների դարան՝ կենդանի նախադիտումով',
    searchPlaceholder: 'Փնտրել դարանում…    սեղմեք /',
    searchLabel: 'Փնտրել դարանում',
    filterLabel: 'Զտել ըստ տեսակի',
    all: 'Բոլորը',
    kind: { component: 'Բաղադրիչներ', prompt: 'Հուշումներ', pattern: 'Ձևանմուշներ' },
    source: { product: 'Պահված', registry: 'Հմտությունների ռեեստր' },
    emptyTitle: 'Դեռ ոչինչ պահված չէ',
    emptyHint: 'Պահված բաղադրիչները, հուշումներն ու ձևանմուշները կհայտնվեն այստեղ։',
    filteredTitle: 'Համընկնումներ չկան',
    filteredHint: 'Ոչինչ չի համընկնում ձեր որոնման և զտիչների հետ։',
    clearFilters: 'Մաքրել որոնումն ու զտիչները',
    unavailableTitle: 'Դարանը դեռ միացված չէ',
    unavailableHint:
      'Աշխատասեղանի դարանի պահեստը և շարժիչի հմտությունների ռեեստրի ընթերցումը դեռ չունեն backend հրաման (ROADMAP Փուլ 4)։ Կեղծ տվյալներ ցույց չեն տրվում — դարանը կհայտնվի այստեղ, երբ այդ հրամանները ավելացվեն։',
    previewEmpty: 'Ընտրեք տարր՝ նախադիտելու համար։',
    listLabel: 'Դարանի արդյունքներ',
    open: 'Բացել',
    close: 'Փակել',
    tags: 'Պիտակներ',
    loadFailed: 'Չհաջողվեց բեռնել դարանը։',
  },
};

type KindFilter = 'all' | LibraryKind;

// ── Live preview panel (labeled, announces selection changes) ────────────────
function PreviewPanel({ item, label, previewLabelFor }: {
  item: LibraryItem | null;
  label: string;
  previewLabelFor: (title: string) => string;
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
            <Badge tone={kindTone[item.kind]}>{item.kind}</Badge>
          </div>
          <div className="muted" style={{ marginBottom: 10 }}>{item.summary}</div>
          <div className="lib-preview-body">
            <pre aria-label={previewLabelFor(item.title)}>{item.preview}</pre>
          </div>
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

  const s = useAsync<LibrarySource>(() => loadLibrarySource(), []);

  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<KindFilter>('all');
  const [selected, setSelected] = useState(0);
  const [openItem, setOpenItem] = useState<LibraryItem | null>(null);

  const searchRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const source = s.data;
  const rawItems: LibraryItem[] = source && source.kind === 'ready' ? source.items : [];

  const q = query.trim().toLowerCase();
  const filtered = rawItems.filter((it) => {
    if (kindFilter !== 'all' && it.kind !== kindFilter) return false;
    if (!q) return true;
    return (
      it.title.toLowerCase().includes(q) ||
      it.summary.toLowerCase().includes(q) ||
      it.tags.some((tg) => tg.toLowerCase().includes(q))
    );
  });

  const sel = filtered.length ? Math.min(selected, filtered.length - 1) : 0;

  // `/` focuses search from anywhere (unless typing); Escape closes the preview.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && openItem) {
        setOpenItem(null);
        return;
      }
      if (e.key !== '/') return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      if (openItem) return;
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [openItem]);

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
    else if (e.key === 'Enter') {
      e.preventDefault();
      const it = filtered[sel];
      if (it) setOpenItem(it);
    }
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

  const countLabel = lang === 'hy'
    ? `${filtered.length} արդյունք`
    : `${filtered.length} ${filtered.length === 1 ? 'result' : 'results'}`;

  const loading = s.loading && s.data === null;
  const chips: KindFilter[] = ['all', 'component', 'prompt', 'pattern'];
  const toolbarVisible = !loading && !s.error && source?.kind === 'ready';

  const renderResults = () => {
    if (loading) return <Skeleton rows={5} />;
    if (s.error) return <ErrorState message={s.error || c.loadFailed} onRetry={s.reload} retryLabel={t('action.retry')} />;
    if (!source || source.kind === 'unavailable') {
      return <EmptyState glyph="❑" title={c.unavailableTitle} hint={c.unavailableHint} />;
    }
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
                  onDoubleClick={() => setOpenItem(it)}
                >
                  <span className="lib-item-top">
                    <span className="lib-item-title">{it.title}</span>
                    <Badge tone={kindTone[it.kind]}>{c.kind[it.kind]}</Badge>
                  </span>
                  <span className="lib-item-sum">{it.summary}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <PreviewPanel item={active} label={c.previewEmpty} previewLabelFor={previewLabelFor} />
      </div>
    );
  };

  return (
    <>
      <style>{LIBRARY_CSS}</style>

      <PageHeader title={t('nav.library')} subtitle={c.subtitle} />

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

      {openItem && (
        <Modal title={openItem.title} onClose={() => setOpenItem(null)}>
          <div className="row" style={{ gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <Badge tone={kindTone[openItem.kind]}>{c.kind[openItem.kind]}</Badge>
            <Badge tone="neutral">{c.source[openItem.source]}</Badge>
          </div>
          <div className="muted" style={{ marginBottom: 12 }}>{openItem.summary}</div>
          <div className="lib-preview-body">
            <pre aria-label={previewLabelFor(openItem.title)}>{openItem.preview}</pre>
          </div>
          {openItem.tags.length > 0 && (
            <div className="lib-tags" aria-label={c.tags}>
              {openItem.tags.map((tg) => <span key={tg} className="lib-tag">{tg}</span>)}
            </div>
          )}
          <div className="form-actions">
            <Button variant="ghost" onClick={() => setOpenItem(null)}>{c.close}</Button>
          </div>
        </Modal>
      )}
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
.lib-count { font-size: 12px; color: var(--brops-muted); font-variant-numeric: tabular-nums; }
.lib-layout { display: grid; grid-template-columns: minmax(240px, 340px) 1fr; gap: var(--menq-space-4); align-items: start; }
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
