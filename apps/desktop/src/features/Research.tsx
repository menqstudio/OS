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
import { STR } from './Research.strings';
import type { ResearchItem } from '../domain/entities';
import type { Lang, Tone } from '../domain/enums';

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

// Localizer: reads the active language and returns the natural-language string
// for `key` (en/hy/ru), falling back to English. `lang` comes from useApp.
type Localize = (k: keyof typeof STR) => string;
const makeL = (lang: Lang): Localize => (k) => STR[k][lang] ?? STR[k].en;

// Machine status id → localized string key (kept separate from the ids/tones).
const STATUS_KEY: Record<ResearchStatus, keyof typeof STR> = {
  open: 'statusOpen',
  in_progress: 'statusInProgress',
  done: 'statusDone',
};

function statusLabel(L: Localize, status: string): string {
  return (RESEARCH_STATUSES as readonly string[]).includes(status)
    ? L(STATUS_KEY[status as ResearchStatus])
    : status;
}

// ── Create form (Modal) — fully wired to the REAL create_research_item command ─
function CreateDialog(
  { onClose, onCreated }: { onClose: () => void; onCreated: (item: ResearchItem) => void },
) {
  const { t, lang } = useApp();
  const L = makeL(lang);

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
    <Modal title={L('newTitle')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <label className="form-row">
        <span className="field-label">{L('fTitle')}</span>
        <Input ref={titleRef} value={title}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{L('fQuestion')}</span>
        <Textarea value={question} style={{ minHeight: 80 }} placeholder={L('questionPlaceholder')}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setQuestion(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{L('fFindings')}</span>
        <Textarea value={findings} style={{ minHeight: 140 }} placeholder={L('findingsPlaceholder')}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFindings(e.target.value)} />
      </label>
      <label className="form-row">
        <span className="field-label">{L('fStatus')}</span>
        <Select value={status} onChange={(e: ChangeEvent<HTMLSelectElement>) => setStatus(e.target.value as ResearchStatus)}>
          {RESEARCH_STATUSES.map((k) => <option key={k} value={k}>{L(STATUS_KEY[k])}</option>)}
        </Select>
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

// ── Delete confirm (Modal) — wired to the REAL delete_research_item command ────
function DeleteDialog(
  { item, onClose, onDeleted }: { item: ResearchItem; onClose: () => void; onDeleted: (id: string) => void },
) {
  const { t, lang } = useApp();
  const L = makeL(lang);
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
    <Modal title={L('deleteTitle')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <p>{L('deletePrompt')}</p>
      <p className="muted"><b>{item.title}</b></p>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="danger" disabled={busy} onClick={confirm}>
          {busy ? L('deleting') : L('deleteLabel')}
        </Button>
      </div>
    </Modal>
  );
}

export function Research() {
  const { t, lang } = useApp();
  const L = makeL(lang);

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
    if (s.error) return <ErrorState message={s.error || L('loadFailed')} onRetry={s.reload} retryLabel={t('action.retry')} />;
    if (filtered.length === 0) {
      return isFiltering ? (
        <div>
          <EmptyState glyph="⌕" title={L('filteredTitle')} hint={L('filteredHint')} />
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <Button small onClick={() => setQuery('')}>{L('clearSearch')}</Button>
          </div>
        </div>
      ) : (
        <EmptyState glyph="⌖" title={L('emptyTitle')} hint={L('emptyHint')} />
      );
    }
    return (
      <div
        ref={listRef}
        className="rsx-list"
        role="listbox"
        aria-label={L('listPanel')}
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
                  <Badge tone={statusTone[r.status] ?? 'neutral'}>{statusLabel(L, r.status)}</Badge>
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
          <EmptyState glyph="⌖" title={L('selectTitle')} hint={L('selectHint')} />
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
              <span className="eyebrow">{L('detailPanel')}</span>
              <h2>{selected.title}</h2>
            </div>
            <Badge tone={statusTone[selected.status] ?? 'neutral'}>{statusLabel(L, selected.status)}</Badge>
          </div>

          <section aria-label={L('question')}>
            <h3>{L('question')}</h3>
            {selected.question
              ? <div className="rsx-body">{selected.question}</div>
              : <div className="muted">{L('noQuestion')}</div>}
          </section>

          <section className="rsx-section" aria-label={L('findings')}>
            <h3>{L('findings')}</h3>
            {selected.findings
              ? <div className="rsx-body">{selected.findings}</div>
              : <div className="muted">{L('noFindings')}</div>}
          </section>

          <section className="rsx-section" aria-label={L('detailPanel')}>
            <div className="rsx-foot">
              <div className="rsx-meta">
                <div className="field">
                  <span className="field-label">{L('created')}</span>
                  <span>{fmtDate(selected.createdAt)}</span>
                </div>
                <div className="field">
                  <span className="field-label">{L('updated')}</span>
                  <span>{fmtDate(selected.updatedAt)}</span>
                </div>
              </div>
              <Button variant="danger" small onClick={() => setDeleting(selected)}>{L('deleteLabel')}</Button>
            </div>
          </section>
        </article>
      </div>
    );
  };

  const toolbarVisible = !loading && !s.error && items.length > 0;
  const statsVisible = !loading && !s.error;

  const stats: Array<{ n: number; label: string; cls?: string }> = [
    { n: items.length, label: L('records'), cls: 'rs-info' },
    { n: counts.open, label: L('statusOpen') },
    { n: counts.in_progress, label: L('statusInProgress') },
    { n: counts.done, label: L('statusDone'), cls: 'rs-mint' },
  ];

  return (
    <div className="v-research">
      <style>{CSS}</style>

      <header className="pageHead reveal">
        <div className="pageHead-lead">
          <Mark state="live" size={34} className="rsx-glyph" />
          <div>
            <span className="eyebrow">{L('eyebrow')}</span>
            <h1>{t('nav.research')}</h1>
            <p className="sub">{L('subtitle')}</p>
          </div>
        </div>
        <div className="right">
          <span className="pill info" aria-live="polite">
            {items.length}&nbsp;· {L('records')}
          </span>
          <Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>
        </div>
      </header>

      {statsVisible && (
        <section className="surface soft rc-metrics rise" aria-label={L('records')}>
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
        <h2>{L('listPanel')}</h2>
        <span className="note">{L('listNote')}</span>
      </div>

      <div className="rsx-grid">
        <section className="rsx-panel surface soft rsx-rail-card" aria-label={L('listPanel')}>
          <div className="rsx-rail">
            {toolbarVisible && (
              <div className="rsx-search">
                <Input
                  ref={searchRef}
                  type="search"
                  role="searchbox"
                  value={query}
                  aria-label={L('searchLabel')}
                  placeholder={L('searchPlaceholder')}
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
