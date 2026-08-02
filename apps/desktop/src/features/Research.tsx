import {
  useEffect, useMemo, useRef, useState,
  type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Input, Textarea, Select, Skeleton, ErrorState, EmptyState, Modal,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { ResearchItem } from '../domain/entities';
import type { Tone } from '../domain/enums';

// ── §D `research` ⌖ Հետազոտում ────────────────────────────────────────────────
// A research record store — a question and its findings, with a status — wired
// end-to-end to the REAL desktop research store (`list_research` /
// `create_research_item`). Mirrors the Knowledge entity pattern precisely: a plain
// SQLite-backed store surfaced through the typed desktop service. No data is
// fabricated — the store's real rows drive every state. (Hard-delete stays
// capability-denied under the Wave-2b L2 policy, exactly like knowledge, so the
// page exposes no delete affordance.)

const RESEARCH_STATUSES = ['open', 'in_progress', 'done'] as const;
type ResearchStatus = (typeof RESEARCH_STATUSES)[number];

const statusTone: Record<string, Tone> = {
  open: 'info',
  in_progress: 'warning',
  done: 'success',
};

interface Copy {
  subtitle: string;
  listPanel: string;
  detailPanel: string;
  searchPlaceholder: string;
  searchLabel: string;
  emptyTitle: string;
  emptyHint: string;
  filteredTitle: string;
  filteredHint: string;
  clearSearch: string;
  selectTitle: string;
  selectHint: string;
  question: string;
  findings: string;
  noQuestion: string;
  noFindings: string;
  created: string;
  updated: string;
  loadFailed: string;
  newTitle: string;
  fTitle: string;
  fQuestion: string;
  fFindings: string;
  fStatus: string;
  questionPlaceholder: string;
  findingsPlaceholder: string;
  saving: string;
  status: Record<ResearchStatus, string>;
}

const COPY: Record<'en' | 'hy', Copy> = {
  en: {
    subtitle: 'Research records — a question, its findings, and status',
    listPanel: 'Research',
    detailPanel: 'Record',
    searchPlaceholder: 'Search research…    press /',
    searchLabel: 'Search research',
    emptyTitle: 'Bro has run no research yet',
    emptyHint: 'Record the first research question to start the log.',
    filteredTitle: 'No matches',
    filteredHint: 'Nothing matches your search.',
    clearSearch: 'Clear search',
    selectTitle: 'Select a record',
    selectHint: 'Pick a research record from the list, or press New to add one.',
    question: 'Question',
    findings: 'Findings',
    noQuestion: 'No question recorded.',
    noFindings: 'No findings recorded yet.',
    created: 'Created',
    updated: 'Updated',
    loadFailed: 'Couldn’t load research.',
    newTitle: 'New research record',
    fTitle: 'Title',
    fQuestion: 'Question',
    fFindings: 'Findings',
    fStatus: 'Status',
    questionPlaceholder: 'What is being researched?',
    findingsPlaceholder: 'What was found…',
    saving: 'Saving…',
    status: { open: 'Open', in_progress: 'In progress', done: 'Done' },
  },
  hy: {
    subtitle: 'Հետազոտման գրառումներ — հարց, գտածոներ և կարգավիճակ',
    listPanel: 'Հետազոտում',
    detailPanel: 'Գրառում',
    searchPlaceholder: 'Փնտրել հետազոտում…    սեղմեք /',
    searchLabel: 'Փնտրել հետազոտում',
    emptyTitle: 'Bro-ն դեռ հետազոտում չի կատարել',
    emptyHint: 'Գրանցիր առաջին հետազոտման հարցը՝ մատյանը սկսելու համար։',
    filteredTitle: 'Համընկնումներ չկան',
    filteredHint: 'Ոչինչ չի համընկնում ձեր որոնման հետ։',
    clearSearch: 'Մաքրել որոնումը',
    selectTitle: 'Ընտրիր գրառում',
    selectHint: 'Ընտրիր հետազոտման գրառում ցանկից կամ սեղմիր «Նոր»՝ ավելացնելու համար։',
    question: 'Հարց',
    findings: 'Գտածոներ',
    noQuestion: 'Հարց գրանցված չէ։',
    noFindings: 'Գտածոներ դեռ գրանցված չեն։',
    created: 'Ստեղծված',
    updated: 'Թարմացված',
    loadFailed: 'Չհաջողվեց բեռնել հետազոտումը։',
    newTitle: 'Նոր հետազոտման գրառում',
    fTitle: 'Վերնագիր',
    fQuestion: 'Հարց',
    fFindings: 'Գտածոներ',
    fStatus: 'Կարգավիճակ',
    questionPlaceholder: 'Ի՞նչ է հետազոտվում',
    findingsPlaceholder: 'Ի՞նչ գտնվեց…',
    saving: 'Պահվում է…',
    status: { open: 'Բաց', in_progress: 'Ընթացքի մեջ', done: 'Ավարտված' },
  },
};

function statusLabel(c: Copy, status: string): string {
  return (RESEARCH_STATUSES as readonly string[]).includes(status)
    ? c.status[status as ResearchStatus]
    : status;
}

// ── Create form (Modal) — fully wired to the REAL create_research_item command ─
function CreateDialog(
  { onClose, onCreated }: { onClose: () => void; onCreated: (item: ResearchItem) => void },
) {
  const { t, lang } = useApp();
  const c = COPY[lang === 'hy' ? 'hy' : 'en'];

  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [findings, setFindings] = useState('');
  const [status, setStatus] = useState<ResearchStatus>('open');
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
      .createResearchItem({ title: title.trim(), question: question.trim(), findings: findings.trim(), status })
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
        <span className="field-label">{c.fQuestion}</span>
        <Textarea value={question} style={{ minHeight: 80 }} placeholder={c.questionPlaceholder}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setQuestion(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{c.fFindings}</span>
        <Textarea value={findings} style={{ minHeight: 140 }} placeholder={c.findingsPlaceholder}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFindings(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{c.fStatus}</span>
        <Select value={status} onChange={(e: ChangeEvent<HTMLSelectElement>) => setStatus(e.target.value as ResearchStatus)}>
          {RESEARCH_STATUSES.map((k) => <option key={k} value={k}>{c.status[k]}</option>)}
        </Select>
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

export function Research() {
  const { t, lang } = useApp();
  const c = COPY[lang === 'hy' ? 'hy' : 'en'];

  const s = useAsync<ResearchItem[]>(() => desktop.listResearch(), []);

  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const items = s.data ?? [];

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

  const q = query.trim().toLowerCase();
  const filtered = items.filter((it) => {
    if (!q) return true;
    return (
      it.title.toLowerCase().includes(q) ||
      it.question.toLowerCase().includes(q) ||
      it.findings.toLowerCase().includes(q)
    );
  });

  const isFiltering = q !== '';
  const activeId = filtered.some((r) => r.id === selectedId) ? selectedId : (filtered[0]?.id ?? null);
  const selected = filtered.find((r) => r.id === activeId) ?? null;

  // `/` focuses search from anywhere (unless typing or the dialog is open).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || creating) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [creating]);

  const onListKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (filtered.length === 0) return;
    const idx = Math.max(0, filtered.findIndex((r) => r.id === activeId));
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      let next = idx;
      if (e.key === 'ArrowDown') next = Math.min(idx + 1, filtered.length - 1);
      else if (e.key === 'ArrowUp') next = Math.max(idx - 1, 0);
      else if (e.key === 'Home') next = 0;
      else next = filtered.length - 1;
      setSelectedId(filtered[next].id);
    }
  };

  const onCreated = (item: ResearchItem) => {
    setCreating(false);
    setQuery('');
    setSelectedId(item.id);
    s.reload();
  };

  const loading = s.loading && s.data === null;

  const renderList = () => {
    if (loading) return <Skeleton rows={5} />;
    if (s.error) return <ErrorState message={s.error || c.loadFailed} onRetry={s.reload} retryLabel={t('action.retry')} />;
    if (filtered.length === 0) {
      return isFiltering ? (
        <div>
          <EmptyState glyph="⌕" title={c.filteredTitle} hint={c.filteredHint} />
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <Button small onClick={() => setQuery('')}>{c.clearSearch}</Button>
          </div>
        </div>
      ) : (
        <EmptyState glyph="⌖" title={c.emptyTitle} hint={c.emptyHint} />
      );
    }
    return (
      <div
        ref={listRef}
        className="rsx-list"
        role="listbox"
        aria-label={c.listPanel}
        aria-activedescendant={activeId ? `rsx-row-${activeId}` : undefined}
        tabIndex={0}
        onKeyDown={onListKey}
      >
        {filtered.map((r, i) => {
          const isSel = r.id === activeId;
          return (
            <div
              key={r.id}
              id={`rsx-row-${r.id}`}
              role="option"
              aria-selected={isSel}
              className={`rsx-row${isSel ? ' rsx-row--sel' : ''}`}
              style={{ animationDelay: `${Math.min(i, 10) * 35}ms` }}
              onClick={() => setSelectedId(r.id)}
            >
              <span className="rsx-row-top">
                <span className="rsx-row-title">{r.title}</span>
                <Badge tone={statusTone[r.status] ?? 'neutral'}>{statusLabel(c, r.status)}</Badge>
              </span>
              {r.question && <span className="rsx-row-sub">{r.question}</span>}
            </div>
          );
        })}
      </div>
    );
  };

  const renderDetail = () => {
    if (loading) return <Panel><Skeleton rows={6} /></Panel>;
    if (s.error) return <Panel><ErrorState message={s.error} onRetry={s.reload} retryLabel={t('action.retry')} /></Panel>;
    if (!selected) {
      return (
        <Panel>
          <EmptyState glyph="⌖" title={c.selectTitle} hint={c.selectHint} />
        </Panel>
      );
    }
    return (
      <Panel>
        <article className="rsx-detail" role="article" aria-label={selected.title}>
          <div className="rsx-detail-head">
            <h2>{selected.title}</h2>
            <Badge tone={statusTone[selected.status] ?? 'neutral'}>{statusLabel(c, selected.status)}</Badge>
          </div>

          <section aria-label={c.question}>
            <h3>{c.question}</h3>
            {selected.question
              ? <div className="rsx-body">{selected.question}</div>
              : <div className="muted">{c.noQuestion}</div>}
          </section>

          <section className="rsx-section" aria-label={c.findings}>
            <h3>{c.findings}</h3>
            {selected.findings
              ? <div className="rsx-body">{selected.findings}</div>
              : <div className="muted">{c.noFindings}</div>}
          </section>

          <section className="rsx-section" aria-label={c.detailPanel}>
            <div className="rsx-meta">
              <div className="field">
                <span className="field-label">{c.created}</span>
                <span>{fmtDate(selected.createdAt)}</span>
              </div>
              <div className="field">
                <span className="field-label">{c.updated}</span>
                <span>{fmtDate(selected.updatedAt)}</span>
              </div>
            </div>
          </section>
        </article>
      </Panel>
    );
  };

  const toolbarVisible = !loading && !s.error && items.length > 0;

  return (
    <>
      <style>{CSS}</style>

      <PageHeader
        title={t('nav.research')}
        subtitle={c.subtitle}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      <div className="chat-layout">
        <Panel title={c.listPanel}>
          <div className="rsx-rail">
            {toolbarVisible && (
              <div className="rsx-search">
                <Input
                  ref={searchRef}
                  type="search"
                  role="searchbox"
                  value={query}
                  aria-label={c.searchLabel}
                  placeholder={c.searchPlaceholder}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)}
                />
              </div>
            )}
            {renderList()}
          </div>
        </Panel>

        <div>{renderDetail()}</div>
      </div>

      {creating && <CreateDialog onClose={() => setCreating(false)} onCreated={onCreated} />}
    </>
  );
}

const CSS = `
.rsx-rail { display: flex; flex-direction: column; gap: var(--menq-space-4); }
.rsx-search { position: relative; }
.rsx-list { display: flex; flex-direction: column; gap: 2px; max-height: 56vh; overflow-y: auto;
  padding-right: 4px; outline: none; border-radius: var(--menq-radius-md); }
.rsx-list:focus-visible { box-shadow: 0 0 0 2px var(--menq-color-focus); }
.rsx-row { display: flex; flex-direction: column; gap: 4px; width: 100%; text-align: left; cursor: pointer;
  padding: 9px 12px; background: var(--brops-surface); color: var(--brops-text);
  border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); font: inherit;
  animation: rsx-reveal var(--menq-motion-med) ease both;
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.rsx-row:hover { background: var(--menq-color-hover); }
.rsx-row--sel { background: var(--menq-color-selected); border-color: var(--brops-accent); }
.rsx-row-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.rsx-row-title { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rsx-row-sub { font-size: 12px; color: var(--brops-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rsx-detail { display: flex; flex-direction: column; gap: var(--menq-space-4);
  animation: rsx-reveal var(--menq-motion-med) ease both; }
.rsx-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--menq-space-3); }
.rsx-detail h2 { font-size: 19px; font-weight: 700; letter-spacing: -0.01em; margin: 0; }
.rsx-detail h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--brops-muted); font-weight: 600; margin: 0 0 6px; }
.rsx-body { line-height: 1.6; white-space: pre-wrap; font-size: 14px; }
.rsx-section { border-top: 1px solid var(--brops-border); padding-top: var(--menq-space-4);
  display: flex; flex-direction: column; gap: var(--menq-space-2); }
.rsx-meta { display: flex; gap: var(--menq-space-5); flex-wrap: wrap; }
@keyframes rsx-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .rsx-row, .rsx-detail { animation: none; }
}
`;
