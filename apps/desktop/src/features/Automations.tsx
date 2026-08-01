import {
  useEffect, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState,
  Modal, FormRow, Input, ConfirmDialog,
} from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Automation } from '../domain/entities';

// ---------------------------------------------------------------------------
// Local, page-scoped styling for the automations cockpit. Lives here (not in a
// shared stylesheet) per the page contract; everything resolves through the
// MenQ/BroPS design tokens — no hard-coded colors — and honours reduced motion.
// ---------------------------------------------------------------------------
const CSS = `
.au-layout { display: grid; grid-template-columns: minmax(260px, 360px) 1fr; gap: var(--menq-space-4); align-items: start; }
@media (max-width: 900px) { .au-layout { grid-template-columns: 1fr; } }

.au-toolbar { display: flex; align-items: center; gap: var(--menq-space-3); margin-bottom: var(--menq-space-3); }
.au-toolbar .input { flex: 1; }
.au-count { font-size: 12px; font-weight: 600; color: var(--brops-muted); white-space: nowrap;
  background: var(--menq-color-hover); border-radius: var(--menq-radius-pill); padding: 3px 10px; font-variant-numeric: tabular-nums; }

.au-list { display: flex; flex-direction: column; gap: var(--menq-space-2); outline: none; }
.au-row { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3);
  width: 100%; text-align: left; font: inherit; cursor: pointer;
  background: transparent; color: var(--brops-text);
  border: 1px solid transparent; border-left: 3px solid transparent;
  border-radius: var(--menq-radius-md); padding: 9px 11px;
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.au-row:hover { background: var(--menq-color-hover); }
.au-row--selected { background: var(--menq-color-selected); border-left-color: var(--brops-accent); }
.au-row:focus-visible { outline: 2px solid var(--brops-accent); outline-offset: 1px; }
.au-row-main { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.au-row-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.au-row-sub { font-size: 12px; color: var(--brops-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* runtime state chip — colour comes from tokens via the --au-c custom prop */
.au-state { display: inline-flex; align-items: center; gap: 6px; flex: none; font-size: 12px; font-weight: 600;
  padding: 2px 9px; border-radius: var(--menq-radius-pill); white-space: nowrap;
  color: var(--au-c); background: color-mix(in srgb, var(--au-c) 14%, transparent); }
.au-state-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--au-c); flex: none; }
.au-state--flowing .au-state-dot { animation: au-pulse 1.4s ease-in-out infinite; }
.au-state--throttled .au-state-dot { animation: au-suspend 1.8s steps(2, jump-none) infinite; }
@keyframes au-pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: .4; transform: scale(.7); } }
@keyframes au-suspend { 0%,49% { opacity: 1; } 50%,100% { opacity: .25; } }

/* schematic / manifold view */
.au-schem { display: flex; align-items: stretch; gap: 0; flex-wrap: wrap; }
.au-node { flex: 1 1 140px; min-width: 0; background: var(--brops-surface);
  border: 1px solid var(--brops-border); border-left: 3px solid var(--au-nc, var(--brops-border));
  border-radius: var(--menq-radius-md); padding: 10px 12px; }
.au-node-kind { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--brops-muted); }
.au-node-val { font-weight: 600; margin-top: 3px; word-break: break-word; }
.au-node--trigger { --au-nc: var(--menq-color-info); }
.au-node--guard { --au-nc: var(--menq-color-accent); }
.au-node--action { --au-nc: var(--menq-color-success); }
.au-conn { flex: 0 0 40px; align-self: center; height: 3px; border-radius: 2px; position: relative; overflow: hidden;
  background: var(--brops-border); }
.au-conn::after { content: ""; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, var(--brops-accent), transparent);
  transform: translateX(-100%); }
.au-conn--flow::after { animation: au-stream 1.6s linear infinite; }
@keyframes au-stream { to { transform: translateX(100%); } }
@media (max-width: 560px) { .au-schem { flex-direction: column; } .au-conn { width: 3px; height: 22px; flex-basis: 22px; margin-left: 18px; } }

/* accessible step-list fallback for the schematic */
.au-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--menq-space-2); }
.au-step { display: flex; gap: var(--menq-space-3); align-items: baseline; }
.au-step-n { font-variant-numeric: tabular-nums; color: var(--brops-muted); font-weight: 700; min-width: 16px; }
.au-step-k { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--brops-muted); min-width: 78px; }
.au-step-v { font-weight: 500; word-break: break-word; }

/* meta cards (scheduler / owner) */
.au-meta { display: grid; grid-template-columns: 1fr 1fr; gap: var(--menq-space-3); }
@media (max-width: 560px) { .au-meta { grid-template-columns: 1fr; } }
.au-meta-card { background: var(--menq-color-hover); border: 1px solid var(--brops-border);
  border-radius: var(--menq-radius-md); padding: 10px 12px; }
.au-meta-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--brops-muted); }
.au-meta-val { margin-top: 3px; font-weight: 600; }
.au-meta-hint { margin-top: 4px; font-size: 12px; color: var(--brops-muted); }

/* blocked panel (wall denial / guard trip) */
.au-blocked { border: 1px solid color-mix(in srgb, var(--menq-color-danger) 40%, transparent);
  background: color-mix(in srgb, var(--menq-color-danger) 10%, transparent);
  border-radius: var(--menq-radius-md); padding: var(--menq-space-4); }
.au-blocked--inline { margin-top: var(--menq-space-3); }
.au-blocked-title { font-weight: 700; color: var(--menq-color-danger); display: flex; align-items: center; gap: 8px; }
.au-blocked-reason { margin-top: 6px; word-break: break-word; }
.au-blocked-fix { margin-top: 8px; font-size: 13px; color: var(--brops-muted); }

/* design-time governance note in the authoring form */
.au-gov { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; color: var(--brops-muted);
  background: var(--menq-color-selected); border: 1px solid var(--brops-border);
  border-radius: var(--menq-radius-md); padding: 8px 10px; margin-bottom: var(--menq-space-4); }

/* keyboard-shortcut hint strip */
.au-kbd { display: flex; flex-wrap: wrap; gap: var(--menq-space-4); margin-top: var(--menq-space-4);
  font-size: 12px; color: var(--brops-muted); }
.au-kbd span { display: inline-flex; align-items: center; gap: 5px; }
.au-kbd kbd { font: inherit; font-size: 11px; background: var(--menq-color-hover);
  border: 1px solid var(--brops-border); border-bottom-width: 2px; border-radius: 5px; padding: 1px 6px; }

/* visually-hidden aria-live status region */
.au-status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.au-detail { display: flex; flex-direction: column; gap: var(--menq-space-4); outline: none; }
.au-detail-head { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3); flex-wrap: wrap; }
.au-section-title { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--brops-muted); font-weight: 600; margin-bottom: var(--menq-space-2); }

@media (prefers-reduced-motion: reduce) {
  .au-conn--flow::after { animation: none; transform: translateX(0); opacity: .5; }
  .au-state--flowing .au-state-dot, .au-state--throttled .au-state-dot { animation: none; }
}
`;

// The full per-automation runtime vocabulary from the §D spec. Only `idle`,
// `off` and `blocked` are derivable from what the desktop store exposes today
// (an `enabled` flag, plus a live wall/guard denial). `flowing`, `throttled`
// and `completed` require the run-history backend that has not shipped yet, so
// they are DEFINED here (colour + motion) but never fabricated onto real rows.
type RuntimeState = 'idle' | 'flowing' | 'throttled' | 'blocked' | 'completed' | 'off';

const STATE_COLOR: Record<RuntimeState, string> = {
  idle: 'var(--menq-color-muted)',
  flowing: 'var(--menq-color-accent)',
  throttled: 'var(--menq-color-warning)',
  blocked: 'var(--menq-color-danger)',
  completed: 'var(--menq-color-success)',
  off: 'var(--menq-color-muted)',
};

/** A wall denial or a tripped guard — distinguished from a plain backend/load
 *  failure so the UI can render the spec's `blocked` state (reason + fix). */
function isDenial(message: string): boolean {
  return /denied|not permitted|permission|guard|blocked|wall|ungoverned|lease|receipt/i.test(message);
}

function NewRuleForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t, lang } = useApp();
  const L = (en: string, hy: string) => (lang === 'hy' ? hy : en);
  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('');
  const [action, setAction] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createAutomation({ name: name.trim(), trigger: trigger.trim(), action: action.trim() })
      .then(() => {
        onCreated();
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('automations.newRule')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      {/* Design-time governance guarantee: authoring cannot produce an ungoverned
          action — every fire is dispatched behind the wall with a verified receipt. */}
      <div className="au-gov" role="note">
        <span aria-hidden="true">🛡</span>
        <span>{L(
          'Every automation runs governed — each fire requires a lease and a verified receipt. Ungoverned actions are refused.',
          'Յուրաքանչյուր ավտոմատ աշխատում է կառավարվող — ամեն գործարկում պահանջում է լիզինգ և հաստատված ստացական։ Չկառավարվող գործողությունները մերժվում են։',
        )}</span>
      </div>
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.trigger')}>
        <Input value={trigger} onChange={(e) => setTrigger(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.action')}>
        <Input value={action} onChange={(e) => setAction(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button type="button" variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button type="button" variant="primary" disabled={busy} onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Automations() {
  const { t, lang } = useApp();
  const L = (en: string, hy: string) => (lang === 'hy' ? hy : en);

  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // A wall/guard denial captured from an enable/disable attempt; drives the
  // per-automation `blocked` runtime state and inline reason + fix.
  const [actionError, setActionError] = useState<{ id: string; message: string } | null>(null);
  const [announce, setAnnounce] = useState('');

  const filterRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const detailRef = useRef<HTMLDivElement | null>(null);

  const s = useAsync(() => desktop.listAutomations(), []);
  const items = s.data ?? [];

  const stateLabel = (st: RuntimeState): string => ({
    idle: L('Idle', 'Սպասում'),
    flowing: L('Flowing', 'Հոսում'),
    throttled: L('Throttled', 'Զսպված'),
    blocked: L('Blocked', 'Արգելափակված'),
    completed: L('Completed', 'Ավարտված'),
    off: L('Off', 'Անջատված'),
  }[st]);

  // Honest state derivation — never fabricates a run it cannot observe.
  const runtimeState = (a: Automation): RuntimeState => {
    if (actionError && actionError.id === a.id) return 'blocked';
    return a.enabled ? 'idle' : 'off';
  };

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;
    return items.filter((a) =>
      a.name.toLowerCase().includes(q)
      || a.trigger.toLowerCase().includes(q)
      || a.action.toLowerCase().includes(q));
  }, [items, filter]);

  const selected = filtered.find((a) => a.id === selectedId) ?? filtered[0] ?? null;

  const toggle = (a: Automation) => {
    const next = !a.enabled;
    desktop
      .setAutomationEnabled(a.id, next)
      .then(() => {
        setActionError(null);
        setAnnounce(`${a.name}: ${next ? t('automations.enabled') : stateLabel('off')}`);
        s.reload();
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e);
        setActionError({ id: a.id, message });
        setAnnounce(isDenial(message)
          ? `${a.name}: ${stateLabel('blocked')}`
          : message);
        s.reload();
      });
  };

  const remove = (id: string) => {
    setPendingDelete(null);
    if (selectedId === id) setSelectedId(null);
    desktop.deleteAutomation(id).then(() => s.reload()).catch(() => s.reload());
  };

  const selectAt = (i: number) => {
    const a = filtered[i];
    if (!a) return;
    setSelectedId(a.id);
    setAnnounce(`${a.name} — ${stateLabel(runtimeState(a))}`);
    requestAnimationFrame(() => {
      listRef.current?.querySelector<HTMLButtonElement>(`[data-id="${a.id}"]`)?.focus();
    });
  };

  // Page-level shortcuts: `n` new, `/` focus filter. Suppressed while typing in
  // a field or while a modal owns the keyboard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (creating || pendingDelete) return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      const inText = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable === true;
      if (inText) return;
      if (e.key === 'n' || e.key === 'N') {
        e.preventDefault();
        setCreating(true);
      } else if (e.key === '/') {
        e.preventDefault();
        filterRef.current?.focus();
        filterRef.current?.select();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [creating, pendingDelete]);

  // Index navigation: arrows move the selection, Enter opens the schematic
  // (focuses the detail pane), Space enables/disables. Bound to the list so it
  // never hijacks the page's other controls.
  const onListKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (filtered.length === 0) return;
    const idx = Math.max(0, filtered.findIndex((a) => a.id === selected?.id));
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectAt(Math.min(filtered.length - 1, idx + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectAt(Math.max(0, idx - 1));
    } else if (e.key === 'Home') {
      e.preventDefault();
      selectAt(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      selectAt(filtered.length - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selected) {
        setAnnounce(`${selected.name} — ${stateLabel(runtimeState(selected))}`);
        detailRef.current?.focus();
      }
    } else if (e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault();
      if (selected) toggle(selected);
    }
  };

  const StateChip = ({ st }: { st: RuntimeState }) => (
    <span
      className={`au-state au-state--${st}`}
      style={{ '--au-c': STATE_COLOR[st] } as CSSProperties}
    >
      <span className="au-state-dot" aria-hidden="true" />
      {stateLabel(st)}
    </span>
  );

  const renderBlocked = (reason: string, fix: string, inline = false) => (
    <div className={`au-blocked${inline ? ' au-blocked--inline' : ''}`} role="alert">
      <div className="au-blocked-title">
        <span aria-hidden="true">⛔</span>
        {L('Blocked by the wall', 'Արգելափակված է պատով')}
      </div>
      <div className="au-blocked-reason">{reason}</div>
      <div className="au-blocked-fix">{fix}</div>
    </div>
  );

  // --- Index panel body: the spec's default / loading / empty / error / blocked --------------
  const renderIndex = () => {
    if (s.loading && s.data === null) return <Skeleton rows={5} />;

    if (s.error) {
      if (!hasBackend()) {
        return <EmptyState glyph="◍" title={t('state.offline')} hint={t('state.offlineHint')} />;
      }
      if (isDenial(s.error)) {
        return renderBlocked(
          `${t('state.permissionDenied')}: ${s.error}`,
          L(
            'This automation store is denied in the current mode or scope. Switch to work mode, or request the required scope/approval, then retry.',
            'Այս ավտոմատների պահեստը մերժված է ընթացիկ ռեժիմում կամ շրջանակում։ Անցեք work ռեժիմ կամ պահանջեք անհրաժեշտ շրջանակ/հաստատում, ապա կրկնեք։',
          ),
        );
      }
      return <ErrorState message={s.error} onRetry={s.reload} />;
    }

    if (items.length === 0) {
      return (
        <div style={{ textAlign: 'center' }}>
          <EmptyState
            title={L('No automations yet', 'Դեռ ավտոմատներ չկան')}
            hint={L(
              'Create your first automation — every run stays governed and verified.',
              'Ստեղծեք ձեր առաջին ավտոմատը — ամեն գործարկում մնում է կառավարվող և հաստատված։',
            )}
          />
          <Button variant="primary" onClick={() => setCreating(true)}>
            {L('Create automation', 'Ստեղծել ավտոմատ')}
          </Button>
        </div>
      );
    }

    return (
      <>
        <div className="au-toolbar">
          <Input
            ref={filterRef}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={L('Filter automations…  ( / )', 'Զտել ավտոմատները…  ( / )')}
            aria-label={L('Filter automations', 'Զտել ավտոմատները')}
          />
          <span className="au-count" aria-hidden="true">
            {filtered.length === items.length ? items.length : `${filtered.length}/${items.length}`}
          </span>
        </div>

        {filtered.length === 0 ? (
          <EmptyState
            glyph="⌕"
            title={L('No matches', 'Համընկնումներ չկան')}
            hint={L('No automation matches your filter.', 'Ոչ մի ավտոմատ չի համապատասխանում զտիչին։')}
          />
        ) : (
          <div
            className="au-list"
            role="list"
            ref={listRef}
            onKeyDown={onListKey}
            aria-label={L('Automations', 'Ավտոմատներ')}
          >
            {filtered.map((a) => {
              const st = runtimeState(a);
              const isSel = a.id === selected?.id;
              return (
                <button
                  key={a.id}
                  type="button"
                  role="listitem"
                  data-id={a.id}
                  tabIndex={isSel ? 0 : -1}
                  aria-current={isSel}
                  aria-label={`${a.name}, ${stateLabel(st)}, ${a.enabled ? t('automations.enabled') : stateLabel('off')}`}
                  className={`au-row${isSel ? ' au-row--selected' : ''}`}
                  onClick={() => {
                    setSelectedId(a.id);
                    setAnnounce(`${a.name} — ${stateLabel(st)}`);
                  }}
                >
                  <span className="au-row-main">
                    <span className="au-row-name">{a.name}</span>
                    <span className="au-row-sub">
                      {(a.trigger || '—')} → {(a.action || '—')}
                    </span>
                  </span>
                  <StateChip st={st} />
                </button>
              );
            })}
          </div>
        )}
      </>
    );
  };

  // --- Detail panel: schematic/manifold + step-list fallback + scheduler + owner -------------
  const renderDetail = () => {
    if (!selected) {
      return (
        <Panel title={L('Automation', 'Ավտոմատ')}>
          <EmptyState
            glyph="⛓"
            title={L('Select an automation', 'Ընտրեք ավտոմատ')}
            hint={L('Choose an automation to view its schematic and schedule.', 'Ընտրեք ավտոմատ՝ դրա սխեման և ժամանակացույցը դիտելու համար։')}
          />
        </Panel>
      );
    }

    const a = selected;
    const st = runtimeState(a);
    const trigger = a.trigger || L('any event', 'ցանկացած իրադարձություն');
    const action = a.action || '—';
    const guard = L('Governed dispatch — verified receipt required', 'Կառավարվող առաքում — պահանջվում է հաստատված ստացական');
    const armed = a.enabled && (st === 'idle' || st === 'flowing');

    return (
      <Panel title={a.name}>
        <div className="au-detail" ref={detailRef} tabIndex={-1}>
          <div className="au-detail-head">
            <StateChip st={st} />
            <div className="row" style={{ gap: 8 }}>
              <Button
                variant="ghost"
                onClick={() => toggle(a)}
                title={L('Space', 'Բացատ')}
              >
                {t(a.enabled ? 'automations.disable' : 'automations.enable')}
              </Button>
              <Button variant="ghost" onClick={() => setPendingDelete(a.id)}>
                {t('action.delete')}
              </Button>
            </div>
          </div>

          {actionError && actionError.id === a.id && isDenial(actionError.message)
            && renderBlocked(
              actionError.message,
              L(
                'A guard tripped or the wall denied this action. Resolve the guard condition or request approval, then retry.',
                'Պահապանը գործարկվեց կամ պատը մերժեց այս գործողությունը։ Լուծեք պահապանի պայմանը կամ պահանջեք հաստատում, ապա կրկնեք։',
              ),
              true,
            )}
          {actionError && actionError.id === a.id && !isDenial(actionError.message) && (
            <div className="form-error">{actionError.message}</div>
          )}

          {/* Visual schematic (manifold). Mirrored, keyboard-independent, and
              hidden from AT — the ordered step-list below is its accessible form. */}
          <div>
            <div className="au-section-title">{L('Schematic', 'Սխեմա')}</div>
            <div className="au-schem" aria-hidden="true">
              <div className="au-node au-node--trigger">
                <div className="au-node-kind">{t('field.trigger')}</div>
                <div className="au-node-val">{trigger}</div>
              </div>
              <div className={`au-conn${armed ? ' au-conn--flow' : ''}`} />
              <div className="au-node au-node--guard">
                <div className="au-node-kind">
                  {L('Guard', 'Պահապան')} <Badge tone="accent">{L('Governed', 'Կառավարվող')}</Badge>
                </div>
                <div className="au-node-val">{guard}</div>
              </div>
              <div className={`au-conn${armed ? ' au-conn--flow' : ''}`} />
              <div className="au-node au-node--action">
                <div className="au-node-kind">{t('field.action')}</div>
                <div className="au-node-val">{action}</div>
              </div>
            </div>
          </div>

          {/* Step-list fallback — the schematic as an ordered, screen-reader-native list. */}
          <div>
            <div className="au-section-title">{L('Steps', 'Քայլեր')}</div>
            <ol className="au-steps" role="list">
              <li className="au-step" role="listitem">
                <span className="au-step-n">1</span>
                <span className="au-step-k">{t('field.trigger')}</span>
                <span className="au-step-v">{trigger}</span>
              </li>
              <li className="au-step" role="listitem">
                <span className="au-step-n">2</span>
                <span className="au-step-k">{L('Guard', 'Պահապան')}</span>
                <span className="au-step-v">{guard}</span>
              </li>
              <li className="au-step" role="listitem">
                <span className="au-step-n">3</span>
                <span className="au-step-k">{t('field.action')}</span>
                <span className="au-step-v">{action}</span>
              </li>
            </ol>
          </div>

          {/* Scheduler + owner. Neither has a backing store today, so both render
              the honest empty state the spec requires rather than invented data. */}
          <div className="au-meta">
            <div className="au-meta-card">
              <div className="au-meta-label">{L('Scheduler', 'Ժամանակացույց')}</div>
              <div className="au-meta-val">{L('No schedule', 'Ժամանակացույց չկա')}</div>
              <div className="au-meta-hint">
                {L(
                  'Scheduled fires need the scheduler backend; connected runs will appear here and in Calendar.',
                  'Ժամանակացույցով գործարկումները պահանջում են ժամանակացույցի backend; միացված գործարկումները կհայտնվեն այստեղ և Օրացույցում։',
                )}
              </div>
            </div>
            <div className="au-meta-card">
              <div className="au-meta-label">{L('Owner', 'Տեր')}</div>
              <div className="au-meta-val">{L('Not recorded', 'Չգրանցված')}</div>
              <div className="au-meta-hint">
                {L(
                  'Owner attribution arrives with the automation store’s owner field.',
                  'Տիրոջ վերագրումը կհասնի ավտոմատների պահեստի owner դաշտի հետ։',
                )}
              </div>
            </div>
          </div>
        </div>
      </Panel>
    );
  };

  return (
    <>
      <style>{CSS}</style>

      <PageHeader
        title={t('nav.automations')}
        subtitle={t('automations.subtitle')}
        actions={(
          <Button variant="primary" onClick={() => setCreating(true)} title={L('New  ( n )', 'Նոր  ( n )')}>
            {t('action.new')}
          </Button>
        )}
      />

      {/* polite live region — announces selection and enable/disable/blocked outcomes */}
      <div className="au-status" role="status" aria-live="polite">{announce}</div>

      {creating && <NewRuleForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

      {pendingDelete && (
        <ConfirmDialog
          title={t('confirm.deleteTitle')}
          message={t('confirm.deleteBody')}
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      <div className="au-layout">
        <Panel title={t('nav.automations')}>
          {renderIndex()}
          <div className="au-kbd" aria-hidden="true">
            <span><kbd>n</kbd> {L('New', 'Նոր')}</span>
            <span><kbd>/</kbd> {L('Filter', 'Զտել')}</span>
            <span><kbd>↑</kbd><kbd>↓</kbd> {L('Navigate', 'Նավարկել')}</span>
            <span><kbd>↵</kbd> {L('Open', 'Բացել')}</span>
            <span><kbd>Space</kbd> {L('Enable / disable', 'Միացնել / անջատել')}</span>
          </div>
        </Panel>

        {renderDetail()}
      </div>
    </>
  );
}
