import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import { Button, Skeleton, ErrorState, EmptyState, Field } from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Integration } from '../domain/entities';
import { STR } from './Integrations.strings';

// ── Health derivation ─────────────────────────────────────────────────────────
// Health is derived from the connector's real `status` field (no fabricated
// data): connected → healthy, error → unhealthy, everything else → not connected.
type Health = 'healthy' | 'unhealthy' | 'idle';
function healthOf(status: string): Health {
  if (status === 'connected') return 'healthy';
  if (status === 'error') return 'unhealthy';
  return 'idle';
}

// aios health-token key (drives the --stc hue on the scoped `.st-*` classes that
// already ship in aios.css). live only when a connector is genuinely connected.
function stKeyOf(h: Health): 'live' | 'error' | 'paused' {
  return h === 'healthy' ? 'live' : h === 'unhealthy' ? 'error' : 'paused';
}

// A backend rejection that reads like a governance/secret refusal is surfaced as
// the spec's `blocked` state (would run ungoverned / needs a desktop secret)
// rather than a generic error.
function isGovernanceBlock(message: string): boolean {
  return /secret|ungoverned|governance|not provisioned|auth|denied|permission|refus/i.test(message);
}

export function Integrations() {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const s = useAsync(() => desktop.listIntegrations(), []);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  // Live region text (aria-live=polite): the last connect/disconnect/refusal.
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error' | 'blocked'; text: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const searchRef = useRef<HTMLInputElement | null>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );

  const items = s.data ?? [];

  // Telemetry — every count derived from the REAL array (never fabricated).
  const totals = useMemo(() => {
    const connected = items.filter((i) => i.status === 'connected').length;
    const attention = items.filter((i) => i.status === 'error').length;
    return { total: items.length, connected, attention, anyConnected: connected > 0 };
  }, [items]);

  // Filter + partition the catalog into "connected" (configured) and "available"
  // (never connected). `error` connectors stay in the connected group so their
  // unhealthy state is visible where an owner expects a working connector.
  const { connected, available, ordered } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (i: Integration) =>
      !q || i.name.toLowerCase().includes(q) || i.provider.toLowerCase().includes(q);
    const filtered = items.filter(match);
    const connected = filtered.filter((i) => i.status !== 'disconnected');
    const available = filtered.filter((i) => i.status === 'disconnected');
    return { connected, available, ordered: [...connected, ...available] };
  }, [items, query]);

  const selected = ordered.find((i) => i.id === selectedId)
    ?? items.find((i) => i.id === selectedId)
    ?? null;

  const healthLabel = (h: Health) =>
    h === 'healthy' ? L('healthConnected')
      : h === 'unhealthy' ? L('healthUnhealthy')
        : L('healthDisconnected');
  // aios pill variant for the health state; error recolours via `.pill.cst-err`.
  const healthPill = (h: Health) =>
    h === 'healthy' ? 'live' : h === 'unhealthy' ? 'warn cst-err' : 'off';

  // ── Enable/disable (Space) + connect/disconnect action ──────────────────────
  const setStatus = (i: Integration, status: 'connected' | 'disconnected') => {
    setBusyId(i.id);
    setNotice(null);
    desktop.setIntegrationStatus(i.id, status)
      .then(() => {
        setBusyId(null);
        setNotice({
          kind: 'ok',
          text: (status === 'connected' ? L('connectedNamed') : L('disconnectedNamed'))
            .replace('{name}', i.name),
        });
        s.reload();
      })
      .catch((e: unknown) => {
        setBusyId(null);
        const msg = e instanceof Error ? e.message : String(e);
        // A refusal to connect (would hold a desktop secret / run ungoverned) is
        // the spec's `blocked` outcome, announced with its reason.
        setNotice({
          kind: status === 'connected' && isGovernanceBlock(msg) ? 'blocked' : 'error',
          text: msg,
        });
        s.reload();
      });
  };

  const toggle = (i: Integration) =>
    setStatus(i, i.status === 'connected' ? 'disconnected' : 'connected');

  // ── Keyboard: `/` focuses catalog search from anywhere on the page ──────────
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if (e.key !== '/' || e.defaultPrevented) return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Roving keyboard on a catalog row: Enter opens (native click), Space toggles
  // enable/disable, Arrow/Home/End move focus between connectors.
  const onRowKeyDown = (e: KeyboardEvent<HTMLButtonElement>, idx: number, i: Integration) => {
    if (e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault();
      if (busyId !== i.id) toggle(i);
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      const last = ordered.length - 1;
      const next = e.key === 'Home' ? 0
        : e.key === 'End' ? last
          : e.key === 'ArrowDown' ? Math.min(last, idx + 1)
            : Math.max(0, idx - 1);
      rowRefs.current[next]?.focus();
    }
  };

  const renderRow = (i: Integration, idx: number) => {
    const h = healthOf(i.status);
    const active = i.id === selectedId;
    // Health/status folded into the accessible name (a11y requirement).
    const aria = `${i.name}, ${i.provider}, ${healthLabel(h)}`;
    return (
      <div role="listitem" key={i.id}>
        <button
          type="button"
          ref={(el) => { rowRefs.current[idx] = el; }}
          className={`creg-row ${active ? 'is-sel' : ''}`}
          aria-label={aria}
          aria-current={active ? 'true' : undefined}
          onClick={() => { setSelectedId(i.id); setNotice(null); }}
          onKeyDown={(e) => onRowKeyDown(e, idx, i)}
        >
          <span className={`cr-dot st-${stKeyOf(h)}`} aria-hidden="true" />
          <span className="cr-main">
            <b>{i.name}</b>
            <span className="micro">{i.provider}</span>
          </span>
          <span className={`pill ${healthPill(h)}`}>{healthLabel(h)}</span>
        </button>
      </div>
    );
  };

  // ── Detail pane for the selected connector ──────────────────────────────────
  const renderDetail = (i: Integration) => {
    const h = healthOf(i.status);
    const created = new Date(i.createdAt);
    const updated = new Date(i.updatedAt);
    return (
      <div className="cst-detail rise" key={i.id}>
        <div className="cd-head">
          <span className={`cd-badge st-${stKeyOf(h)}`} aria-hidden="true" />
          <div className="cd-id">
            <span className="eyebrow">{i.provider} · {L('channel')}</span>
            <b>{i.name}</b>
          </div>
          <span className={`pill ${healthPill(h)}`}>{healthLabel(h)}</span>
        </div>

        {/* error state — connector unhealthy */}
        {i.status === 'error' && (
          <div className="intg-blocked intg-blocked--error" role="alert">
            <div className="intg-blocked-title">⚠ {L('connectorUnhealthy')}</div>
            <div className="micro">
              {L('connectorUnhealthyBody')}
            </div>
            <div style={{ marginTop: 10 }}>
              <Button small variant="primary" disabled={busyId === i.id} onClick={() => setStatus(i, 'connected')}>
                {L('reconnect')}
              </Button>
            </div>
          </div>
        )}

        {/* per-connector config (real fields; the desktop holds no config schema/secret) */}
        <section aria-label={L('configuration')}>
          <div className="intg-section-title">{L('configuration')}</div>
          <div className="intg-fields">
            <Field label={L('provider')}>{i.provider}</Field>
            <Field label={L('status')}>
              <span className={`pill ${healthPill(h)}`}>{healthLabel(h)}</span>
            </Field>
            <Field label={L('added')}>
              {isNaN(created.getTime()) ? '—' : dateFmt.format(created)}
            </Field>
            <Field label={L('lastChecked')}>
              {isNaN(updated.getTime()) ? '—' : dateFmt.format(updated)}
            </Field>
          </div>
        </section>

        {/* auth handoff — clearly labeled; the desktop stores NO external secret */}
        <section aria-label={L('authentication')}>
          <div className="intg-section-title">{L('authentication')}</div>
          <div className="intg-auth">
            <span className="pill info">{L('handoff')}</span>
            <p className="micro" style={{ margin: '8px 0 0' }}>
              {L('authBody')}
            </p>
          </div>
        </section>

        {/* inbound triggers + outbound sinks — no backing command exists yet, so
            the honest `blocked` state (not provisioned + how to provision). */}
        <section aria-label={L('triggersSinks')}>
          <div className="intg-section-title">{L('triggersSinksTitle')}</div>
          <div className="intg-blocked" role="note">
            <div className="intg-blocked-title">🔒 {L('mappingNotProvisioned')}</div>
            <div className="micro">
              {L('mappingBody')}
            </div>
            <div className="intg-provision">
              <div className="eyebrow">{L('howToProvision')}</div>
              <ol className="intg-steps">
                <li>{L('provisionStep1')}</li>
                <li>{L('provisionStep2')}</li>
                <li>{L('provisionStep3')}</li>
              </ol>
            </div>
          </div>
        </section>

        {/* primary action (enable/disable) */}
        <div className="cd-foot">
          {i.status === 'connected' ? (
            <Button variant="ghost" disabled={busyId === i.id} onClick={() => setStatus(i, 'disconnected')}>
              {t('integrations.disconnect')}
            </Button>
          ) : (
            <Button variant="primary" disabled={busyId === i.id} onClick={() => setStatus(i, 'connected')}>
              {t('integrations.connect')}
            </Button>
          )}
        </div>
      </div>
    );
  };

  const loading = s.loading && s.data === null;

  return (
    <div className="v-integrations">
      <IntegrationsStyle />

      {/* ── HEADER ─────────────────────────────────────────────────────────── */}
      <header className="pageHead">
        <div>
          <span className="eyebrow">{L('headerEyebrow')}</span>
          <h1>{t('nav.integrations')}</h1>
          <p className="sub">{t('integrations.subtitle')}</p>
        </div>
        <div className="right">
          {!loading && !s.error && (
            <span className={`pill ${totals.anyConnected ? 'live' : 'off'}`}>
              {totals.connected} {L('connectedLower')}
            </span>
          )}
          <Mark state={totals.anyConnected ? 'live' : 'idle'} size={30} />
        </div>
      </header>

      {/* live region: connect / disconnect / refusal announcements */}
      <div className="intg-live" role="status" aria-live="polite">
        {notice && (
          <div className={`intg-notice intg-notice--${notice.kind}`}>
            {notice.kind === 'blocked' && <span aria-hidden="true">🔒 </span>}
            {notice.kind === 'error' && <span aria-hidden="true">⚠ </span>}
            {notice.kind === 'blocked'
              ? `${L('blocked')}: ${notice.text}`
              : notice.text}
          </div>
        )}
      </div>

      {/* ── HERO · real-derived telemetry band ─────────────────────────────── */}
      {!loading && !s.error && items.length > 0 && (
        <section className="surface soft lg hud intg-hero" aria-label={L('integrationOverview')}>
          <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
          <div className="intg-stats">
            <span className="capsule"><b>{totals.total}</b><span>{L('integrationsUnit')}</span></span>
            <span className="capsule"><b>{totals.connected}</b><span>{L('activeChannel')}</span></span>
            <span className={`capsule ${totals.attention > 0 ? 'is-warn' : ''}`}><b>{totals.attention}</b><span>{L('attention')}</span></span>
          </div>
          {/* The travelling `live` pulse is earned only when a connector is REALLY
              connected; with zero connected it is a still divider, not a feed. */}
          <div className={`wire${totals.anyConnected ? ' live' : ''}`} aria-hidden="true" />
          <p className="micro intg-scale">
            {L('stateScale')}
          </p>
        </section>
      )}

      <div className="intg-layout">
        {/* ── REGISTRY · the real connector catalog ─────────────────────────── */}
        <section className="surface soft intg-registry" aria-label={L('connectorCatalog')}>
          <div className="sec-head">
            <h2>{L('connectionRegistry')}</h2>
            <span className="note">{L('selectRowHint')}</span>
          </div>

          <div className="intg-search">
            <input
              ref={searchRef}
              className="input"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={L('searchPlaceholder')}
              aria-label={L('searchAria')}
            />
          </div>

          {loading ? (
            <Skeleton rows={5} />
          ) : s.error ? (
            <ErrorState message={s.error} onRetry={s.reload} />
          ) : items.length === 0 ? (
            // empty state: no integrations + browse CTA
            <EmptyState
              glyph="🔌"
              title={L('noIntegrations')}
              hint={L('noIntegrationsHint')}
            />
          ) : ordered.length === 0 ? (
            <EmptyState
              glyph="🔎"
              title={L('noMatches')}
              hint={L('noMatchesHint')}
            />
          ) : (
            <div className="creg">
              {connected.length > 0 && (
                <div className="creg-group">
                  <div className="creg-head"><span className="creg-gname">{L('groupConnected')}</span></div>
                  <div role="list" aria-label={L('connectedConnectors')} className="intg-list">
                    {connected.map((i) => renderRow(i, ordered.indexOf(i)))}
                  </div>
                </div>
              )}
              {available.length > 0 && (
                <div className="creg-group">
                  <div className="creg-head"><span className="creg-gname">{L('groupAvailable')}</span></div>
                  <div role="list" aria-label={L('availableConnectors')} className="intg-list">
                    {available.map((i) => renderRow(i, ordered.indexOf(i)))}
                  </div>
                </div>
              )}
              {!hasBackend() && (
                <div className="micro intg-hint">{t('state.offlineBanner')}</div>
              )}
            </div>
          )}
        </section>

        {/* ── DETAIL · selected connector ───────────────────────────────────── */}
        <section className="surface soft intg-board" aria-label={L('connectorDetail')}>
          {selected ? (
            renderDetail(selected)
          ) : (
            <EmptyState
              glyph="🔌"
              title={L('selectConnector')}
              hint={L('selectConnectorHint')}
            />
          )}
        </section>
      </div>
    </div>
  );
}

// Scoped styles for this page (kept inside the feature file per the build
// contract). Colors/spacing resolve through the shared aios design tokens;
// motion honours prefers-reduced-motion. Health hues come from the `.st-*`
// tokens already defined under `.v-integrations` in aios.css.
function IntegrationsStyle() {
  return (
    <style>{`
.v-integrations .intg-hero { position:relative; padding:var(--s5) var(--s6); margin-bottom:var(--s5);
  display:flex; flex-direction:column; gap:var(--s3); }
.v-integrations .intg-stats { display:flex; flex-wrap:wrap; gap:var(--s3); }
.v-integrations .intg-stats .capsule.is-warn { color:var(--warning);
  border-color:rgb(var(--warning-rgb)/.3); background:rgb(var(--warning-rgb)/.08); }
.v-integrations .intg-stats .capsule.is-warn b { color:var(--warning); }
.v-integrations .intg-scale { color:var(--ink-muted); margin:0; }

.v-integrations .intg-layout { display:grid; grid-template-columns:minmax(260px,380px) 1fr;
  gap:var(--s5); align-items:start; }
@media (max-width:860px){ .v-integrations .intg-layout { grid-template-columns:1fr; } }

.v-integrations .intg-registry, .v-integrations .intg-board { padding:var(--s5); }

.v-integrations .intg-live { min-height:0; }
.v-integrations .intg-notice { margin-bottom:var(--s4); padding:9px 13px; border-radius:var(--r);
  font-size:var(--t-small); border:1px solid rgb(var(--line-rgb)/.8); background:rgb(var(--raised-rgb)/.5); color:var(--ink); }
.v-integrations .intg-notice--ok { border-color:rgb(var(--success-rgb)/.4); background:rgb(var(--success-rgb)/.09); }
.v-integrations .intg-notice--error { border-color:rgb(var(--danger-rgb)/.4); background:rgb(var(--danger-rgb)/.09); }
.v-integrations .intg-notice--blocked { border-color:rgb(var(--warning-rgb)/.4); background:rgb(var(--warning-rgb)/.09); }

.v-integrations .intg-search { margin:var(--s3) 0 var(--s4); }

.v-integrations .creg { display:flex; flex-direction:column; gap:var(--s4); }
.v-integrations .creg-head { display:flex; align-items:baseline; gap:8px; margin-bottom:6px; }
.v-integrations .creg-gname { font-family:var(--f-mono); font-size:var(--t-micro); text-transform:uppercase;
  letter-spacing:.1em; color:var(--ink-muted); }
.v-integrations .intg-list { display:flex; flex-direction:column; gap:5px; }

.v-integrations .creg-row { display:flex; align-items:center; gap:11px; width:100%; text-align:left;
  background:rgb(var(--raised-rgb)/.4); color:var(--ink); cursor:pointer;
  border:1px solid rgb(var(--line-rgb)/.6); border-radius:var(--r); padding:10px 12px; font:inherit;
  transition:border-color .14s, background .14s; }
.v-integrations .creg-row:hover { background:rgb(var(--raised-rgb)/.8); border-color:rgb(var(--cyan-rgb)/.3); }
.v-integrations .creg-row.is-sel { border-color:rgb(var(--cyan-rgb)/.55);
  box-shadow:0 0 18px rgb(var(--cyan-rgb)/.12), inset 0 0 14px rgb(var(--cyan-rgb)/.05); }
.v-integrations .cr-main { display:flex; flex-direction:column; gap:1px; min-width:0; flex:1; }
.v-integrations .cr-main b { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.v-integrations .cr-main .micro { color:var(--ink-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.v-integrations .creg-row .pill { flex:0 0 auto; }

.v-integrations .cr-dot { width:9px; height:9px; border-radius:50%; flex:none;
  background:rgb(var(--stc,var(--muted-rgb))/.95); box-shadow:0 0 9px rgb(var(--stc,var(--muted-rgb))/.7); }
.v-integrations .cr-dot.st-live { animation:intgPulse 2.4s ease-in-out infinite; }

@keyframes intgPulse { 0%,100%{ box-shadow:0 0 9px rgb(var(--stc)/.7); } 50%{ box-shadow:0 0 15px rgb(var(--stc)/.95); } }

.v-integrations .cst-detail { display:flex; flex-direction:column; gap:var(--s4); }
.v-integrations .cd-head { display:flex; align-items:center; gap:11px; }
.v-integrations .cd-badge { width:12px; height:12px; border-radius:50%; flex:none;
  background:rgb(var(--stc,var(--muted-rgb))/.95); box-shadow:0 0 12px rgb(var(--stc,var(--muted-rgb))/.7); }
.v-integrations .cd-id { min-width:0; flex:1; }
.v-integrations .cd-id b { display:block; font-family:var(--f-display,inherit); font-size:17px; font-weight:700; }
.v-integrations .cd-head .pill { flex:0 0 auto; }

.v-integrations .intg-section-title { font-weight:600; font-size:var(--t-small); margin-bottom:8px; }
.v-integrations .intg-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--s3); }
@media (max-width:560px){ .v-integrations .intg-fields { grid-template-columns:1fr; } }

.v-integrations .intg-auth { border:1px solid rgb(var(--line-rgb)/.8); border-radius:var(--r); padding:var(--s3); }

.v-integrations .intg-blocked { border:1px dashed rgb(var(--line-rgb)/.9); border-radius:var(--r);
  padding:var(--s4); background:rgb(var(--raised-rgb)/.45); }
.v-integrations .intg-blocked .micro { color:var(--ink-muted); }
.v-integrations .intg-blocked--error { border-style:solid; border-color:rgb(var(--danger-rgb)/.45);
  background:rgb(var(--danger-rgb)/.08); }
.v-integrations .intg-blocked-title { font-weight:600; margin-bottom:6px; }
.v-integrations .intg-provision { margin-top:var(--s3); }
.v-integrations .intg-steps { margin:6px 0 0; padding-left:18px; color:var(--ink-muted);
  display:flex; flex-direction:column; gap:4px; }

.v-integrations .cd-foot { display:flex; gap:10px; flex-wrap:wrap; }
.v-integrations .intg-hint { color:var(--ink-muted); margin-top:var(--s3); }

@media (prefers-reduced-motion:reduce){ .v-integrations .cr-dot.st-live { animation:none; } }
    `}</style>
  );
}
