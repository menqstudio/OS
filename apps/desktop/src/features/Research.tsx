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
import { heldLabel, heldNoteKey } from './Research.provenance';
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

// ── §D: the governed run ───────────────────────────────────────────────────────
//
// Phase 5 pairs "governed research produces verified receipts" with "results save to
// knowledge", and §D adds a `blocked` state for "governed provider off / sidecar down → no
// result". None of it existed: this page was a local CRUD list with no run, no receipt and no
// refusal — the one page in the phase whose whole point is that it crosses the wall.
//
// It runs through `stream_ask`, which is the SAME governed path chat uses: buffered, verified
// desktop-side, and the answer held server-side under a one-time id rather than streamed into
// the window. That last part is why saving is a backend command taking the id — the app window
// never receives the text, so it cannot save something the engine did not produce (P1-6).
//
// In the shipped app this will render `blocked`, because the production gate is deliberately
// shut. That is not a placeholder for a working run; it IS the working run, reporting what the
// wall said. A version of this page that showed an answer today would be lying.
type RunState =
  | { k: 'idle' }
  | { k: 'running' }
  | { k: 'held'; resultId: string; provenance: string }
  | { k: 'saved' }
  | { k: 'blocked'; reason: string }
  | { k: 'failed'; reason: string };

function GovernedRun({ item, L }: { item: ResearchItem; L: Localize }) {
  const [run, setRun] = useState<RunState>({ k: 'idle' });
  const cancelled = useRef(false);

  // A new record is a new run. Without this, selecting another item keeps the previous
  // record's held id on screen — and saving it would file one question's answer under
  // another question's title.
  useEffect(() => {
    cancelled.current = false;
    setRun({ k: 'idle' });
    return () => { cancelled.current = true; };
  }, [item.id]);

  const question = (item.question ?? '').trim();
  const start = () => {
    if (!question || run.k === 'running') return;
    cancelled.current = false;
    setRun({ k: 'running' });
    void desktop.streamAsk(question, (ev) => {
      if (cancelled.current) return;
      // `delta` is ignored on purpose: a governed ask is buffered by construction and the
      // body is held, not streamed. Painting deltas here would show text that the verify
      // step may still refuse.
      if (ev.type === 'ready') {
        setRun({ k: 'held', resultId: ev.resultId, provenance: ev.provenance });
      }
      else if (ev.type === 'blocked') setRun({ k: 'blocked', reason: ev.reason });
      else if (ev.type === 'error') setRun({ k: 'failed', reason: ev.message });
    }).catch((e: unknown) => {
      if (!cancelled.current) {
        setRun({ k: 'failed', reason: e instanceof Error ? e.message : String(e) });
      }
    });
  };
  const cancel = () => { cancelled.current = true; setRun({ k: 'idle' }); };
  const save = () => {
    if (run.k !== 'held') return;
    const { resultId } = run;
    void desktop.saveAskToKnowledge(resultId, item.title)
      .then(() => setRun({ k: 'saved' }))
      .catch((e: unknown) => setRun({ k: 'failed', reason: e instanceof Error ? e.message : String(e) }));
  };

  return (
    <section
      className="rsx-section rsx-run"
      aria-label={L('runPanel')}
      onKeyDown={(e) => {
        // §D: "`Enter` run, `Esc` cancel". Not while typing — this panel has no field today,
        // but a keymap that assumes that stops being true the first time one is added.
        const tag = (e.target as HTMLElement).tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (e.key === 'Enter' && run.k !== 'running') { e.preventDefault(); start(); }
        else if (e.key === 'Escape' && run.k === 'running') { e.preventDefault(); cancel(); }
      }}
    >
      <div className="sec-head">
        <h3>{L('runPanel')}</h3>
        {run.k === 'running' && <span className="pill info">{L('running')}</span>}
        {run.k === 'held' && (() => {
          const b = heldLabel(run.provenance);
          return <span className={`pill ${b.tone}`}>{b.glyph} {L(b.key)}</span>;
        })()}
        {run.k === 'saved' && <span className="pill success">✓ {L('savedToKnowledge')}</span>}
      </div>

      {!question ? (
        <p className="muted">{L('needQuestion')}</p>
      ) : (
        <>
          <div className="rsx-run-actions">
            <Button
              small
              variant="primary"
              onClick={start}
              disabled={run.k === 'running'}
            >
              {run.k === 'running' ? L('running') : L('runIt')}
            </Button>
            {run.k === 'held' && (
              <Button small onClick={save}>{L('saveToKnowledge')}</Button>
            )}
          </div>
          <p className="micro muted">{L('runHint')}</p>
        </>
      )}

      {/* The outcome. `role="status"` for the ones that are progress, `role="alert"` for the
          two that mean the thing the owner asked for did not happen. */}
      {run.k === 'held' && (
        <p className="rsx-run-out" role="status">{L(heldNoteKey(run.provenance))}</p>
      )}
      {run.k === 'blocked' && (
        <p className="rsx-run-out rsx-run-out--blocked" role="alert">
          <span className="pill warn">⛒ {L('runBlocked')}</span>
          <span className="micro muted">{L('runBlockedNote')}</span>
          <span className="rsx-run-reason">{run.reason}</span>
        </p>
      )}
      {run.k === 'failed' && (
        <p className="rsx-run-out rsx-run-out--failed" role="alert">
          <span className="pill bad">⚠ {L('runFailed')}</span>
          <span className="rsx-run-reason">{run.reason}</span>
        </p>
      )}
    </section>
  );
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

          <GovernedRun item={selected} L={L} />

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
          {/* Posture from the REAL `list_research` read — `live` here was on in every
              state, including a failed read. */}
          <Mark
            state={s.error ? 'alert' : loading ? 'thinking' : 'idle'}
            size={34}
            className="rsx-glyph"
          />
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
          {/* Plain divider. `wire.live` animates a travelling pulse that reads as a
              running feed; this page issues one `list_research` read and has none. */}
          <div className="wire" aria-hidden="true" />
        </section>
      )}

      <div className="sec-head">
        <h2>{L('listPanel')}</h2>
        <span className="note">{L('listNote')}</span>
      </div>

      <div className="rsx-grid">
        <section className="rsx-panel surface soft" aria-label={L('listPanel')}>
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
/* The governed run. A refusal is bordered and deliberate rather than a loose pill: it is a
   decision the wall made, and it is the state this page will be in until the gate opens. */
.v-research .rsx-run-actions { display: flex; gap: var(--s3); flex-wrap: wrap; margin-bottom: 6px; }
.v-research .rsx-run-out { display: flex; flex-direction: column; gap: 6px; margin: var(--s3) 0 0;
  padding: 10px 12px; border-radius: var(--r); background: rgb(var(--surface-rgb)/.5);
  border: 1px solid rgb(var(--line-rgb)/.9); }
.v-research .rsx-run-out--blocked { background: rgb(var(--warning-rgb)/.07);
  border-color: rgb(var(--warning-rgb)/.32); }
.v-research .rsx-run-out--failed { background: rgb(var(--danger-rgb)/.07);
  border-color: rgb(var(--danger-rgb)/.3); }
.v-research .rsx-run-reason { font-family: var(--f-mono); font-size: 12px;
  color: var(--ink-muted); word-break: break-word; }
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
