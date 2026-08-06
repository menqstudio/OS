import {
  useEffect, useMemo, useRef, useState, type CSSProperties,
  type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  Button, Skeleton, ErrorState, EmptyState, Input, Textarea, ConfirmDialog,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { KnowledgeNote } from '../domain/entities';
import { STR, fmt } from './Knowledge.strings';

// ---------------------------------------------------------------------------
// §D `knowledge` page — re-skinned to the brops-aios «Նեյրո-քարտեզ / Neural
// Map» mockup. Every value shown is REAL: the desktop knowledge store
// (`list_knowledge` / `search_knowledge` / `create_knowledge` /
// `delete_knowledge`). The mockup's fabricated instruments — the plotted synapse
// field (per-note graph coordinates, edges, adjacency), the "recall heat" node
// sizing, the fixed "14 nodes · 21 synapses · 4 domains · 92% recall" counters
// and the recall/day telemetry — have NO backing in the `KnowledgeNote` entity
// and are therefore OMITTED, never faked. Collections are a real grouping over
// the notes' `tags`; the honest metric strip counts only real facts. Where the
// store records nothing (an update/edit command) the page renders the honest
// "not wired" affordance. Motion honours prefers-reduced-motion via aios.css.
// ---------------------------------------------------------------------------

// A "collection" is a real grouping over the notes' `tags` field (there is no
// separate collection store command). ALL and UNTAGGED are sentinel ids that can
// never collide with a real tag: ALL is the empty string, UNTAGGED is a control
// char no tag can contain.
const COLLECTION_ALL = '';
const COLLECTION_UNTAGGED = ' untagged';

function parseTags(note: KnowledgeNote): string[] {
  return note.tags.split(',').map((x) => x.trim()).filter(Boolean);
}

function snippet(body: string): string {
  const flat = body.replace(/\s+/g, ' ').trim();
  return flat.length > 96 ? `${flat.slice(0, 96)}…` : flat;
}

/** The article editor. Creating a NEW article is fully wired to the real
 *  `create_knowledge` command. Editing an EXISTING article renders the honest
 *  `blocked` state: the desktop knowledge store exposes no update command, so no
 *  edit is fabricated or silently dropped. */
function ArticleEditor(
  { note, onCancel, onSaved }:
  { note: KnowledgeNote | null; onCancel: () => void; onSaved: (created: KnowledgeNote) => void },
) {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const isEdit = note !== null;

  const [title, setTitle] = useState(note?.title ?? '');
  const [body, setBody] = useState(note?.body ?? '');
  const [source, setSource] = useState(note?.source ?? '');
  const [tags, setTags] = useState(note?.tags ?? '');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const titleRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => { titleRef.current?.focus(); }, []);

  const canSave = !isEdit && title.trim().length > 0 && !busy;

  const submit = () => {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    desktop
      .createKnowledge({ title: title.trim(), body: body.trim(), source: source.trim(), tags: tags.trim() })
      .then((created) => onSaved(created))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  // Full editor keymap: Cmd/Ctrl+S or Cmd/Ctrl+Enter saves; Esc cancels.
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    } else if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'Enter')) {
      e.preventDefault();
      submit();
    }
  };

  const heading = isEdit ? L('editArticle') : t('knowledge.newNote');

  return (
    <section className="surface soft kb-panel">
      <div className="sec-head">
        <h2>{heading}</h2>
        <span className="note">{L('codexEditor')}</span>
      </div>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div className="kb-editor" onKeyDown={onKey} role="group" aria-label={L('articleEditor')}>
        {isEdit && (
          <div className="kb-blocked" role="note">
            <div className="kb-blocked-glyph" aria-hidden="true">✎⃠</div>
            <div className="kb-blocked-title">{L('editNotAvailable')}</div>
            <div className="kb-blocked-body">
              {L('editBlockedBody')}
            </div>
          </div>
        )}

        {error && <div className="form-error">{error}</div>}

        <label className="form-row">
          <span className="field-label">{t('field.title')}</span>
          <Input ref={titleRef} value={title} disabled={isEdit}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} />
        </label>
        <label className="form-row">
          <span className="field-label">{t('field.description')}</span>
          <Textarea value={body} disabled={isEdit} style={{ minHeight: 160 }}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setBody(e.target.value)} />
        </label>
        <label className="form-row">
          <span className="field-label">{t('knowledge.source')}</span>
          <Input value={source} disabled={isEdit} placeholder={L('sourcePlaceholder')}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setSource(e.target.value)} />
        </label>
        <label className="form-row">
          <span className="field-label">{t('knowledge.tags')}</span>
          <Input value={tags} disabled={isEdit} placeholder={L('tagsPlaceholder')}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setTags(e.target.value)} />
        </label>

        <div className="row between kb-editor-foot">
          <span className="kb-keyhint">
            <span className="kb-kbd">⌘/Ctrl</span> + <span className="kb-kbd">S</span> {L('toSave')}
            {'  ·  '}
            <span className="kb-kbd">Esc</span> {L('toCancel')}
          </span>
          <div className="row" style={{ gap: 'var(--s3)' }}>
            <Button variant="ghost" onClick={onCancel}>{t('action.cancel')}</Button>
            <Button
              variant="primary"
              disabled={!canSave}
              title={isEdit ? L('editExistingBlocked') : undefined}
              onClick={submit}
            >
              {t('action.save')}
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Knowledge() {
  const { t, lang, focus, clearFocus } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

  const [query, setQuery] = useState('');
  const [collection, setCollection] = useState<string>(COLLECTION_ALL);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Editor target: `null` closed, `'new'` a blank article, or an existing note
  // (opened read-only into the honest blocked edit state).
  const [editor, setEditor] = useState<'new' | KnowledgeNote | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [announce, setAnnounce] = useState('');

  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  // Data source: the desktop knowledge store. `search_knowledge` drives the
  // article list (server-side search); `list_knowledge` gives a stable, query-
  // independent set for the collections rail. Both are real Tauri commands.
  const s = useAsync(() => desktop.searchKnowledge(query), [query]);
  const all = useAsync(() => desktop.listKnowledge(), []);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium' }),
    [lang],
  );
  const fmtDate = (raw: string): string => {
    const v = raw?.trim();
    if (!v) return '—';
    const d = new Date(isNaN(Number(v)) ? v : Number(v));
    return isNaN(d.getTime()) ? v : dateFmt.format(d);
  };

  // Collections derived from the full (unfiltered) note set: All, one per tag,
  // and Untagged when any note carries no tag. A real grouping over real data.
  const collections = useMemo(() => {
    const notes = all.data ?? [];
    const counts = new Map<string, number>();
    let untagged = 0;
    for (const n of notes) {
      const tags = parseTags(n);
      if (tags.length === 0) untagged += 1;
      for (const tag of tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
    const tagList = [...counts.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([name, count]) => ({ id: name, label: `#${name}`, count }));
    const out: { id: string; label: string; count: number }[] = [
      { id: COLLECTION_ALL, label: L('allArticles'), count: notes.length },
      ...tagList,
    ];
    if (untagged > 0) out.push({ id: COLLECTION_UNTAGGED, label: L('untagged'), count: untagged });
    return out;
  }, [all.data, lang]);

  // A collection whose tag has disappeared falls back to All.
  const activeCollection = collections.some((c) => c.id === collection) ? collection : COLLECTION_ALL;

  // Article list = search results, then narrowed to the active collection.
  const articles = useMemo(() => {
    const list = s.data ?? [];
    if (activeCollection === COLLECTION_ALL) return list;
    if (activeCollection === COLLECTION_UNTAGGED) return list.filter((n) => parseTags(n).length === 0);
    return list.filter((n) => parseTags(n).includes(activeCollection));
  }, [s.data, activeCollection]);

  const isFiltering = query.trim() !== '' || activeCollection !== COLLECTION_ALL;

  // Resolve the selected article: honour an explicit selection when it is still
  // in the list, else fall back to the first article.
  const activeId = articles.some((a) => a.id === selectedId) ? selectedId : (articles[0]?.id ?? null);
  const selected = articles.find((a) => a.id === activeId) ?? null;

  // Honest metric strip — derived ENTIRELY from the real note array. The mockup's
  // fixed graph counters (14 nodes, 21 synapses, 4 domains, 92% recall) and its
  // recall telemetry have no backing in the store, so they are omitted; only
  // honestly-countable facts appear here.
  const notes = all.data ?? [];
  const tagCount = useMemo(
    () => collections.filter((c) => c.id !== COLLECTION_ALL && c.id !== COLLECTION_UNTAGGED).length,
    [collections],
  );
  const citedCount = useMemo(() => notes.filter((n) => n.source.trim()).length, [notes]);
  const metrics = useMemo(() => [
    { v: notes.length, label: L('metricArticles'), tone: '' },
    { v: tagCount, label: L('metricCollections'), tone: 'info' },
    { v: citedCount, label: L('metricCited'), tone: 'mint' },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [notes.length, tagCount, citedCount, lang]);

  // Deep-link consumer: a pending `knowledge` focus selects and reveals the
  // matching article once the list has loaded, then clears focus. If the note is
  // absent from a fully-loaded list we still clear focus to avoid a stuck state.
  useEffect(() => {
    if (focus?.kind !== 'knowledge' || s.loading || !s.data) return;
    const target = s.data.find((n) => n.id === focus.id);
    if (target) setSelectedId(target.id);
    clearFocus();
  }, [focus, s.data, s.loading, clearFocus]);

  // `/` focuses the search box from anywhere on the page (unless already typing
  // in a field or the editor is open).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || editor) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editor]);

  // Announce result counts to assistive tech when a search/filter is active.
  useEffect(() => {
    if (s.loading) return;
    if (!isFiltering) { setAnnounce(''); return; }
    const n = articles.length;
    setAnnounce(fmt.articlesFound(lang, n));
  }, [articles.length, isFiltering, s.loading, lang]);

  const reloadAll = () => { s.reload(); all.reload(); };

  const onCreated = (created: KnowledgeNote) => {
    setEditor(null);
    setSelectedId(created.id);
    setCollection(COLLECTION_ALL);
    setQuery('');
    setAnnounce(fmt.articleSaved(lang, created.title));
    reloadAll();
  };

  const removeArticle = (id: string) => {
    const gone = articles.find((a) => a.id === id);
    setPendingDelete(null);
    setEditor(null);
    if (selectedId === id) setSelectedId(null);
    setAnnounce(gone ? fmt.articleDeleted(lang, gone.title) : '');
    desktop.deleteKnowledge(id).then(reloadAll).catch(reloadAll);
  };

  // Arrow / Home / End navigation across the article list; Enter opens (selects).
  const onListKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (articles.length === 0) return;
    const idx = Math.max(0, articles.findIndex((a) => a.id === activeId));
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      let next = idx;
      if (e.key === 'ArrowDown') next = Math.min(idx + 1, articles.length - 1);
      else if (e.key === 'ArrowUp') next = Math.max(idx - 1, 0);
      else if (e.key === 'Home') next = 0;
      else next = articles.length - 1;
      setSelectedId(articles[next].id);
    }
  };

  const loading = s.loading && s.data === null;

  const renderList = () => {
    if (loading) return <Skeleton rows={5} />;
    if (s.error) return <ErrorState message={s.error} onRetry={s.reload} />;
    if (articles.length === 0) {
      // Two honest, distinct empty states: a filtered-empty when a search/filter
      // is narrowing, versus a genuinely empty store.
      return isFiltering ? (
        <EmptyState
          glyph="⁂"
          title={L('noMatchTitle')}
          hint={L('noMatchHint')}
        />
      ) : (
        <EmptyState
          glyph="⁂"
          title={L('emptyTitle')}
          hint={L('emptyHint')}
        />
      );
    }
    return (
      <div
        ref={listRef}
        className="kb-list"
        role="listbox"
        aria-label={L('articlesLabel')}
        aria-activedescendant={activeId ? `kb-row-${activeId}` : undefined}
        tabIndex={0}
        onKeyDown={onListKey}
      >
        {articles.map((n, i) => {
          const isSel = n.id === activeId;
          const tags = parseTags(n);
          return (
            <div
              key={n.id}
              id={`kb-row-${n.id}`}
              role="option"
              aria-selected={isSel}
              className={`kb-row${isSel ? ' kb-row--sel' : ''}`}
              style={{ animationDelay: `${Math.min(i, 10) * 35}ms` }}
              onClick={() => setSelectedId(n.id)}
            >
              <span className="kb-row-ix" aria-hidden="true">
                <span className="kb-row-dot" />
                <b className="mono">{String(i + 1).padStart(2, '0')}</b>
              </span>
              <span className="kb-row-main">
                <span className="kb-row-title">{n.title}</span>
                {n.body && <span className="kb-row-snippet">{snippet(n.body)}</span>}
                {(n.source || tags.length > 0) && (
                  <span className="kb-row-tags">
                    {n.source && <span className="tag info">{n.source}</span>}
                    {tags.map((tag) => <span key={tag} className="tag">#{tag}</span>)}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  const renderReading = () => {
    if (editor) {
      return (
        <ArticleEditor
          key={editor === 'new' ? 'new' : editor.id}
          note={editor === 'new' ? null : editor}
          onCancel={() => setEditor(null)}
          onSaved={onCreated}
        />
      );
    }
    if (loading) return <section className="surface soft kb-panel"><Skeleton rows={6} /></section>;
    if (s.error) {
      return (
        <section className="surface soft kb-panel">
          <ErrorState message={s.error} onRetry={s.reload} />
        </section>
      );
    }
    if (!selected) {
      return (
        <section className="surface soft kb-panel kb-reading-empty">
          <div className="kb-core-head">
            <Mark state="thinking" size={40} />
            <div className="kb-core-id">
              <span className="eyebrow">{L('codexCore')}</span>
              <b>{L('selectArticle')}</b>
            </div>
          </div>
          <EmptyState
            glyph="⁂"
            title={L('selectArticle')}
            hint={L('selectArticleHint')}
          />
        </section>
      );
    }
    const tags = parseTags(selected);
    return (
      <section className="surface soft kb-panel">
        <span className="bracket tl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
        {/* article role + structured headings (h2 title, h3 section labels). */}
        <article className="kb-article" role="article" aria-label={selected.title}>
          <div className="kb-article-head">
            <div className="kb-article-id">
              <span className="eyebrow">{L('knowledgeNode')}</span>
              <h2>{selected.title}</h2>
            </div>
            <div className="row kb-article-acts" style={{ gap: 'var(--s2)' }}>
              <Button
                small
                onClick={() => setEditor(selected)}
                title={L('openEditor')}
              >
                {t('action.edit')}
              </Button>
              <span className="kb-forget">
                <Button
                  small
                  variant="ghost"
                  onClick={() => setPendingDelete(selected.id)}
                  title={L('deleteArticle')}
                >
                  {t('action.delete')}
                </Button>
              </span>
            </div>
          </div>

          <section aria-label={L('articleBody')}>
            {selected.body
              ? <div className="kb-body">{selected.body}</div>
              : <div className="muted">{L('noBody')}</div>}
          </section>

          {/* Citation view — the note's `source` rendered as a numbered citation. */}
          <section className="kb-section" aria-label={L('citations')}>
            <h3>{L('citation')}</h3>
            {selected.source ? (
              <div className="kb-cite">
                <span className="kb-cite-mark mono">[1]</span>
                <span className="kb-cite-src">{selected.source}</span>
              </div>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>
                {L('noSource')}
              </div>
            )}
          </section>

          {tags.length > 0 && (
            <section className="kb-section" aria-label={t('knowledge.tags')}>
              <h3>{t('knowledge.tags')}</h3>
              <div className="row kb-article-tags" style={{ gap: 8, flexWrap: 'wrap' }}>
                {tags.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className="tag kb-tag-btn"
                    onClick={() => { setCollection(tag); setEditor(null); }}
                    title={fmt.filterToTag(lang, tag)}
                  >
                    #{tag}
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="kb-section" aria-label={L('details')}>
            <div className="kb-meta">
              <span className="capsule">
                <b>{fmtDate(selected.createdAt)}</b>
                <span>{L('created')}</span>
              </span>
              <span className="capsule">
                <b>{fmtDate(selected.updatedAt)}</b>
                <span>{L('updated')}</span>
              </span>
            </div>
          </section>
        </article>
      </section>
    );
  };

  return (
    <div className="v-knowledge">
      <style>{KNOWLEDGE_CSS}</style>

      <header className="pageHead">
        <div>
          <span className="eyebrow">{L('knowledgeBaseEyebrow')}</span>
          <h1>{t('nav.knowledge')}</h1>
          <p className="sub">{t('knowledge.subtitle')}</p>
        </div>
        <div className="right">
          <span className="pill info">{L('recallActive')}</span>
          <Button variant="primary" onClick={() => { setEditor('new'); }}>{t('action.new')}</Button>
        </div>
      </header>

      {/* Polite live region — announces result counts and save/delete outcomes. */}
      <div className="kb-sr-live" role="status" aria-live="polite">{announce}</div>

      {pendingDelete && (
        <ConfirmDialog
          title={t('confirm.deleteTitle')}
          message={t('confirm.deleteBody')}
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => removeArticle(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      <div className="kboard">
        {/* ── FTS index · article browser ───────────────────────────────── */}
        <section className="surface soft hud kb-browser">
          <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />

          <div className="sec-head">
            <h2>{L('searchIndex')}</h2>
            <span className="note">
              <b className="mono">{articles.length}</b>{' / '}
              <b className="mono">{notes.length}</b>{' '}
              {L('nodes')}
            </span>
          </div>

          <div className="kb-search">
            <span className="kb-search-ic" aria-hidden="true">⌕</span>
            <Input
              ref={searchRef}
              type="search"
              role="searchbox"
              value={query}
              aria-label={t('knowledge.search')}
              placeholder={`${t('knowledge.search')}   ( / )`}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)}
            />
          </div>

          {/* Collections — real groupings over the notes' tags, as FTS chips. */}
          {collections.length > 1 && (
            <div className="kb-chips" role="group" aria-label={L('collections')}>
              {collections.map((c) => (
                <button
                  key={c.id || 'all'}
                  type="button"
                  className={`chip kb-chip${c.id === activeCollection ? ' on' : ''}`}
                  aria-pressed={c.id === activeCollection}
                  onClick={() => { setCollection(c.id); setEditor(null); }}
                >
                  <span className="kb-chip-name">{c.label}</span>
                  <span className="kb-chip-count mono">{c.count}</span>
                </button>
              ))}
            </div>
          )}

          {renderList()}
        </section>

        {/* ── Reading / editor rail ─────────────────────────────────────── */}
        <div className="kb-reading" aria-live="polite">{renderReading()}</div>
      </div>

      {/* ── Honest metric strip (real derived counts only) ─────────────── */}
      {!s.error && notes.length > 0 && (
        <section className="surface soft kb-metrics">
          <div className="sec-head">
            <h2>{L('knowledgeBase')}</h2>
            <span className="note">{L('countedFromStore')}</span>
          </div>
          <div className="kstats">
            {metrics.map((x, i) => (
              <div
                key={i}
                className={`kstat${x.tone ? ` ks-${x.tone}` : ''}`}
                style={{ ['--i' as string]: i + 3 } as CSSProperties}
              >
                <b className="mono num">{x.v}</b>
                <span className="micro">{x.label}</span>
              </div>
            ))}
          </div>
          <div className="wire live" aria-hidden="true" />
        </section>
      )}
    </div>
  );
}

// Local styles — scoped under `.v-knowledge`; reuse aios tokens. The synapse-
// field hero, its edges/adjacency graph and the recall telemetry from the mockup
// are intentionally NOT rendered (their data is fabricated); these styles dress
// the real browser · reading-rail · honest-metric surfaces only.
const KNOWLEDGE_CSS = `
.v-knowledge .kb-sr-live { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.v-knowledge .kboard { display: grid; grid-template-columns: minmax(320px, 460px) 1fr;
  gap: var(--s5); align-items: start; }
.v-knowledge .kb-browser, .v-knowledge .kb-panel, .v-knowledge .kb-metrics { padding: var(--s5); }
.v-knowledge .kb-browser { display: grid; gap: var(--s4); }
.v-knowledge .kb-reading { display: grid; gap: var(--s5); min-width: 0; }
.v-knowledge .kb-metrics { margin-top: var(--s6); }

.v-knowledge .kb-search { position: relative; }
.v-knowledge .kb-search .input { padding-left: 34px; }
.v-knowledge .kb-search-ic { position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  color: var(--cyan-soft); font-size: 15px; pointer-events: none; }

.v-knowledge .kb-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.v-knowledge .kb-chip { height: 28px; padding: 0 10px; cursor: pointer; }
.v-knowledge .kb-chip.on { color: var(--cyan-soft); border-color: rgb(var(--cyan-rgb)/.45);
  box-shadow: 0 0 16px rgb(var(--cyan-rgb)/.12); }
.v-knowledge .kb-chip-count { color: var(--ink-muted); font-size: var(--t-micro); }
.v-knowledge .kb-chip.on .kb-chip-count { color: var(--cyan-soft); }

.v-knowledge .kb-list { display: flex; flex-direction: column; gap: 6px; max-height: 60vh; overflow-y: auto;
  padding-right: 4px; outline: none; border-radius: var(--r); }
.v-knowledge .kb-list:focus-visible { box-shadow: 0 0 0 2px rgb(var(--cyan-rgb)/.4); }
.v-knowledge .kb-row { display: flex; gap: 10px; width: 100%; text-align: left; cursor: pointer;
  padding: 10px 12px; background: rgb(var(--raised-rgb)/.4); color: var(--ink);
  border: 1px solid rgb(var(--line-rgb)/.7); border-radius: var(--r);
  animation: kb-reveal var(--slow) ease both;
  transition: background var(--fast), border-color var(--fast), transform var(--fast); }
.v-knowledge .kb-row:hover { border-color: rgb(var(--cyan-rgb)/.35); transform: translateY(-1px); }
.v-knowledge .kb-row--sel { border-color: rgb(var(--cyan-rgb)/.55); background: rgb(var(--cyan-rgb)/.08); }
.v-knowledge .kb-row-ix { display: flex; flex-direction: column; align-items: center; gap: 4px; padding-top: 2px;
  color: var(--ink-muted); font-size: var(--t-micro); }
.v-knowledge .kb-row-dot { width: 6px; height: 6px; border-radius: 50%; background: rgb(var(--cyan-rgb)/.5);
  box-shadow: 0 0 8px rgb(var(--cyan-rgb)/.6); }
.v-knowledge .kb-row--sel .kb-row-dot { background: var(--cyan); }
.v-knowledge .kb-row-main { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
.v-knowledge .kb-row-title { font-weight: 600; font-size: 14px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.v-knowledge .kb-row-snippet { font-size: 12px; color: var(--ink-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.v-knowledge .kb-row-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }

.v-knowledge .kb-panel { position: relative; }
.v-knowledge .kb-reading-empty { display: grid; gap: var(--s4); }
.v-knowledge .kb-core-head, .v-knowledge .kb-article-head { display: flex; align-items: flex-start;
  justify-content: space-between; gap: var(--s4); }
.v-knowledge .kb-core-id, .v-knowledge .kb-article-id { display: grid; gap: 6px; min-width: 0; }
.v-knowledge .kb-core-id b { font-family: var(--f-display); font-size: 16px; }

.v-knowledge .kb-article { display: flex; flex-direction: column; gap: var(--s4);
  animation: kb-reveal var(--slow) ease both; }
.v-knowledge .kb-article h2 { font-size: var(--t-h1); font-weight: 800; letter-spacing: -.01em; margin: 0; }
.v-knowledge .kb-article h3 { font-size: var(--t-micro); text-transform: uppercase; letter-spacing: .14em;
  color: var(--ink-muted); font-weight: 700; margin: 0; }
.v-knowledge .kb-article-acts { flex-shrink: 0; }
.v-knowledge .kb-forget { display: inline-flex; }
.v-knowledge .kb-forget:hover .btn { color: var(--danger); border-color: rgb(var(--danger-rgb)/.4); }
.v-knowledge .kb-body { line-height: 1.6; white-space: pre-wrap; font-size: 14px; }
.v-knowledge .kb-section { border-top: 1px solid rgb(var(--line-rgb)/.6); padding-top: var(--s4);
  display: flex; flex-direction: column; gap: var(--s2); }
.v-knowledge .kb-cite { display: flex; align-items: baseline; gap: var(--s3); font-size: 13px; }
.v-knowledge .kb-cite-mark { color: var(--cyan-soft); font-weight: 700; }
.v-knowledge .kb-cite-src { word-break: break-word; }
.v-knowledge .kb-tag-btn { cursor: pointer; font: inherit; }
.v-knowledge .kb-tag-btn:hover { color: var(--cyan-soft); border-color: rgb(var(--cyan-rgb)/.4); }
.v-knowledge .kb-meta { display: flex; gap: var(--s3); flex-wrap: wrap; }

.v-knowledge .kb-editor { display: flex; flex-direction: column; gap: var(--s4); }
.v-knowledge .kb-editor-foot { flex-wrap: wrap; gap: var(--s3); }
.v-knowledge .kb-keyhint { font-size: 11px; color: var(--ink-muted); }
.v-knowledge .kb-kbd { font-family: var(--f-mono); font-size: 11px; padding: 1px 5px;
  border: 1px solid rgb(var(--line-rgb)/.7); border-radius: var(--r-sm); background: rgb(var(--raised-rgb)/.5); }

.v-knowledge .kb-blocked { display: flex; flex-direction: column; align-items: center; gap: 6px;
  text-align: center; padding: var(--s5) var(--s4);
  border: 1px solid rgb(var(--warning-rgb)/.4); border-radius: var(--r);
  background: rgb(var(--warning-rgb)/.08); }
.v-knowledge .kb-blocked-glyph { font-size: 24px; color: var(--warning); }
.v-knowledge .kb-blocked-title { font-weight: 700; color: var(--ink); }
.v-knowledge .kb-blocked-body { max-width: 460px; color: var(--ink-muted); font-size: 13px; }

.v-knowledge .kstats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--s4); margin-top: var(--s4); }
.v-knowledge .kstat { display: flex; flex-direction: column; gap: 5px; padding: 12px 14px;
  border: 1px solid rgb(var(--line-rgb)/.7); border-radius: var(--r); background: rgb(var(--raised-rgb)/.4);
  animation: kb-reveal var(--slow) ease both; animation-delay: calc(var(--i, 3) * 40ms); }
.v-knowledge .kstat b { font-family: var(--f-display); font-size: 26px; }
.v-knowledge .kstat.ks-info b { color: var(--cyan-soft); }
.v-knowledge .kstat.ks-mint b { color: var(--mint); }

@keyframes kb-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

@media (max-width: 980px) {
  .v-knowledge .kboard { grid-template-columns: 1fr; }
  .v-knowledge .kb-list { max-height: none; }
}
@media (prefers-reduced-motion: reduce) {
  .v-knowledge .kb-row, .v-knowledge .kb-article, .v-knowledge .kstat { animation: none; }
  .v-knowledge .kb-row:hover { transform: none; }
}
`;
