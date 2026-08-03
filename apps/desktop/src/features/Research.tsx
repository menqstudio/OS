import {
  useEffect, useMemo, useRef, useState,
  type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  Button, Badge, Input, Textarea, Select, Skeleton, ErrorState, EmptyState, Modal,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { ResearchItem } from '../domain/entities';
import type { Tone } from '../domain/enums';

// ── §D `research` ⌖ Հետազոտում — reskinned to the brops-aios "Research Observatory"
// mockup (aios.css `.v-research`). The mockup's crucible hero runs on fabricated
// claims / sources / confidence beams; NONE of that is invented here. Presentation
// only is re-dressed — every state stays wired end-to-end to the REAL desktop
// research store (`list_research` / `create_research_item` / `delete_research_item`).
// The observatory telemetry strip is derived purely from the real record array
// (totals + per-status counts); no counts are fabricated.

const RESEARCH_STATUSES = ['open', 'in_progress', 'done'] as const;
type ResearchStatus = (typeof RESEARCH_STATUSES)[number];

const statusTone: Record<string, Tone> = {
  open: 'info',
  in_progress: 'warning',
  done: 'success',
};

// Decorative eyebrow lifted verbatim from the mockup header (no data bound).
const EYEBROW = 'ՀԵՏԱԶՈՏԱԿԱՆ ԴԻՏԱԿԵՏ · RESEARCH OBSERVATORY';

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
  records: string;
  listNote: string;
  deleteLabel: string;
  deleteTitle: string;
  deletePrompt: string;
  deleting: string;
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
    records: 'Records',
    listNote: 'Real records from the store — select one to open it.',
    deleteLabel: 'Delete',
    deleteTitle: 'Delete research record',
    deletePrompt: 'This permanently removes the record.',
    deleting: 'Deleting…',
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
    records: 'Գրառումներ',
    listNote: 'Իրական գրառումներ պահոցից — ընտրիր՝ բացելու համար։',
    deleteLabel: 'Ջնջել',
    deleteTitle: 'Ջնջել հետազոտման գրառումը',
    deletePrompt: 'Սա ընդմիշտ հեռացնում է գրառումը։',
    deleting: 'Ջնջվում է…',
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

// ── Delete confirm (Modal) — wired to the REAL delete_research_item command ────
function DeleteDialog(
  { item, onClose, onDeleted }: { item: ResearchItem; onClose: () => void; onDeleted: (id: string) => void },
) {
  const { t, lang } = useApp();
  const c = COPY[lang === 'hy' ? 'hy' : 'en'];
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const confirm = () => {
    setBusy(true);
    setError(null);
    desktop
      .deleteResearchItem(item.id)
      .then(() => onDeleted(item.id))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={c.deleteTitle} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <p>{c.deletePrompt}</p>
      <p className="muted"><b>{item.title}</b></p>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="danger" disabled={busy} onClick={confirm}>
          {busy ? c.deleting : c.deleteLabel}
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
  const [deleting, setDeleting] = useState<ResearchItem | null>(null);

  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const items = s.data ?? [];

  // Observatory telemetry — derived ONLY from the real record array.
  const counts = useMemo(() => {
    const by: Record<ResearchStatus, number> = { open: 0, in_progress: 0, done: 0 };
    for (const it of items) {
      if ((RESEARCH_STATUSES as readonly string[]).includes(it.status)) by[it.status as ResearchStatus] += 1;
    }
    return by;
  }, [items]);

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

  // `/` focuses search from anywhere (unless typing or a dialog is open).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || creating || deleting) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [creating, deleting]);

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

  const onDeleted = (id: string) => {
    setDeleting(null);
    setSelectedId((cur) => (cur === id ? null : cur));
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
              <span className="rsx-row-dot" data-status={r.status} aria-hidden="true" />
              <span className="rsx-row-body">
                <span className="rsx-row-top">
                  <span className="rsx-row-title">{r.title}</span>
                  <Badge tone={statusTone[r.status] ?? 'neutral'}>{statusLabel(c, r.status)}</Badge>
                </span>
                {r.question && <span className="rsx-row-sub">{r.question}</span>}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  const renderDetail = () => {
    if (loading) return <div className="rsx-panel surface soft"><Skeleton rows={6} /></div>;
    if (s.error) {
      return (
        <div className="rsx-panel surface soft">
          <ErrorState message={s.error} onRetry={s.reload} retryLabel={t('action.retry')} />
        </div>
      );
    }
    if (!selected) {
      return (
        <div className="rsx-panel surface soft">
          <EmptyState glyph="⌖" title={c.selectTitle} hint={c.selectHint} />
        </div>
      );
    }
    return (
      <div className="rsx-panel surface soft lg hud">
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
        <article className="rsx-detail" role="article" aria-label={selected.title}>
          <div className="rsx-detail-head">
            <div className="rsx-detail-heading">
              <span className="eyebrow">{c.detailPanel}</span>
              <h2>{selected.title}</h2>
            </div>
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
            <div className="rsx-foot">
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
              <Button variant="danger" small onClick={() => setDeleting(selected)}>{c.deleteLabel}</Button>
            </div>
          </section>
        </article>
      </div>
    );
  };

  const toolbarVisible = !loading && !s.error && items.length > 0;
  const statsVisible = !loading && !s.error;

  const stats: Array<{ n: number; label: string; cls?: string }> = [
    { n: items.length, label: c.records, cls: 'rs-info' },
    { n: counts.open, label: c.status.open },
    { n: counts.in_progress, label: c.status.in_progress },
    { n: counts.done, label: c.status.done, cls: 'rs-mint' },
  ];

  return (
    <div className="v-research">
      <style>{CSS}</style>

      <header className="pageHead reveal">
        <div className="pageHead-lead">
          <Mark state="live" size={34} className="rsx-glyph" />
          <div>
            <span className="eyebrow">{EYEBROW}</span>
            <h1>{t('nav.research')}</h1>
            <p className="sub">{c.subtitle}</p>
          </div>
        </div>
        <div className="right">
          <span className="pill info" aria-live="polite">
            {items.length}&nbsp;· {c.records}
          </span>
          <Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>
        </div>
      </header>

      {statsVisible && (
        <section className="surface soft rc-metrics rise" aria-label={c.records}>
          <div className="rc-stats" aria-live="polite">
            {stats.map((st) => (
              <div key={st.label} className={`rc-stat${st.cls ? ` ${st.cls}` : ''}`}>
                <b className="count num">{st.n}</b>
                <span className="micro">{st.label}</span>
              </div>
            ))}
          </div>
          <div className="wire live" aria-hidden="true" />
        </section>
      )}

      <div className="sec-head">
        <h2>{c.listPanel}</h2>
        <span className="note">{c.listNote}</span>
      </div>

      <div className="rsx-grid">
        <section className="rsx-panel surface soft rsx-rail-card" aria-label={c.listPanel}>
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
        </section>

        <div>{renderDetail()}</div>
      </div>

      {creating && <CreateDialog onClose={() => setCreating(false)} onCreated={onCreated} />}
      {deleting && <DeleteDialog item={deleting} onClose={() => setDeleting(null)} onDeleted={onDeleted} />}
    </div>
  );
}

const CSS = `
.v-research .pageHead-lead { display: flex; align-items: flex-start; gap: 14px; }
.v-research .rsx-glyph { flex: 0 0 auto; margin-top: 2px; }
.v-research .pageHead .sub { margin-top: 6px; }

.v-research .rc-metrics { margin-bottom: var(--s6); }

.v-research .rsx-grid { display: grid; grid-template-columns: minmax(0, 340px) minmax(0, 1fr);
  gap: var(--s4); align-items: start; }
@media (max-width: 900px) { .v-research .rsx-grid { grid-template-columns: 1fr; } }

.v-research .rsx-panel { padding: var(--s5); }
.v-research .rsx-rail { display: flex; flex-direction: column; gap: var(--s4); }
.v-research .rsx-search { position: relative; }

.v-research .rsx-list { display: flex; flex-direction: column; gap: 8px; max-height: 60vh;
  overflow-y: auto; padding-right: 4px; outline: none; border-radius: var(--r); }
.v-research .rsx-list:focus-visible { box-shadow: 0 0 0 2px var(--cyan-soft); }

.v-research .rsx-row { display: grid; grid-template-columns: auto 1fr; align-items: start; gap: 10px;
  width: 100%; text-align: left; cursor: pointer; padding: 11px 12px; border-radius: var(--r);
  border: 1px solid rgb(var(--line-rgb) / .85); background: rgb(var(--raised-rgb) / .5);
  animation: rsx-reveal var(--enter) both;
  transition: border-color var(--fast), background var(--fast), transform var(--fast); }
.v-research .rsx-row:hover { border-color: rgb(var(--cyan-rgb) / .35); transform: translateX(2px); }
.v-research .rsx-row--sel { border-color: rgb(var(--cyan-rgb) / .5); background: rgb(var(--cyan-rgb) / .08);
  box-shadow: inset 2px 0 0 var(--cyan), 0 0 24px -8px rgb(var(--cyan-rgb) / .35); }
.v-research .rsx-row-dot { width: 8px; height: 8px; margin-top: 6px; border-radius: 50%;
  background: var(--ink-muted); box-shadow: 0 0 8px currentColor; color: var(--ink-muted); }
.v-research .rsx-row-dot[data-status="open"] { background: var(--cyan); color: var(--cyan); }
.v-research .rsx-row-dot[data-status="in_progress"] { background: var(--warning); color: var(--warning); }
.v-research .rsx-row-dot[data-status="done"] { background: var(--success); color: var(--success); }
.v-research .rsx-row-body { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.v-research .rsx-row-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.v-research .rsx-row-title { font-family: var(--f-display); font-weight: 600; font-size: 14px;
  letter-spacing: -.01em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.v-research .rsx-row-sub { font-size: 12px; color: var(--ink-muted); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }

.v-research .rsx-detail { display: flex; flex-direction: column; gap: var(--s4);
  animation: rsx-reveal var(--enter) both; }
.v-research .rsx-detail-head { display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--s3); }
.v-research .rsx-detail-heading { display: grid; gap: 6px; min-width: 0; }
.v-research .rsx-detail h2 { font-family: var(--f-display); font-size: 22px; font-weight: 800;
  letter-spacing: -.02em; margin: 0; }
.v-research .rsx-detail h3 { font-family: var(--f-mono); font-size: var(--t-micro); text-transform: uppercase;
  letter-spacing: .14em; color: var(--ink-muted); font-weight: 700; margin: 0 0 6px; }
.v-research .rsx-body { line-height: 1.6; white-space: pre-wrap; font-size: 14px; }
.v-research .rsx-section { border-top: 1px solid rgb(var(--line-rgb) / .7); padding-top: var(--s4);
  display: flex; flex-direction: column; gap: var(--s2); }
.v-research .rsx-foot { display: flex; align-items: flex-end; justify-content: space-between;
  gap: var(--s4); flex-wrap: wrap; }
.v-research .rsx-meta { display: flex; gap: var(--s5); flex-wrap: wrap; }

@keyframes rsx-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .v-research .rsx-row, .v-research .rsx-detail { animation: none; }
}
`;
