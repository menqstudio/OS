import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState, Field,
} from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone, type Tone } from '../domain/enums';
import type { Integration } from '../domain/entities';

// ── Health derivation ─────────────────────────────────────────────────────────
// Health is derived from the connector's real `status` field (no fabricated
// data): connected → healthy, error → unhealthy, everything else → not connected.
type Health = 'healthy' | 'unhealthy' | 'idle';
function healthOf(status: string): Health {
  if (status === 'connected') return 'healthy';
  if (status === 'error') return 'unhealthy';
  return 'idle';
}

// A backend rejection that reads like a governance/secret refusal is surfaced as
// the spec's `blocked` state (would run ungoverned / needs a desktop secret)
// rather than a generic error.
function isGovernanceBlock(message: string): boolean {
  return /secret|ungoverned|governance|not provisioned|auth|denied|permission|refus/i.test(message);
}

export function Integrations() {
  const { t, lang } = useApp();
  const L = (en: string, hy: string) => (lang === 'hy' ? hy : en);
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
    h === 'healthy' ? L('Healthy', 'Կայուն')
      : h === 'unhealthy' ? L('Unhealthy', 'Անսարք')
        : L('Not connected', 'Չմիացված');
  const healthTone = (h: Health): Tone =>
    h === 'healthy' ? 'success' : h === 'unhealthy' ? 'danger' : 'neutral';

  // ── Enable/disable (Space) + connect/disconnect action ──────────────────────
  const setStatus = (i: Integration, status: 'connected' | 'disconnected') => {
    setBusyId(i.id);
    setNotice(null);
    desktop.setIntegrationStatus(i.id, status)
      .then(() => {
        setBusyId(null);
        setNotice({
          kind: 'ok',
          text: status === 'connected'
            ? L(`${i.name} connected`, `${i.name}՝ միացված է`)
            : L(`${i.name} disconnected`, `${i.name}՝ անջատված է`),
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
          className={`intg-row ${active ? 'intg-row--active' : ''}`}
          aria-label={aria}
          aria-current={active ? 'true' : undefined}
          onClick={() => { setSelectedId(i.id); setNotice(null); }}
          onKeyDown={(e) => onRowKeyDown(e, idx, i)}
        >
          <span className="row" style={{ gap: 8, minWidth: 0 }}>
            <span className={`intg-dot intg-dot--${h}`} aria-hidden="true" />
            <span className="intg-row-name">{i.name}</span>
            <span className="muted intg-row-provider">{i.provider}</span>
          </span>
          <Badge tone={statusTone[i.status] ?? 'neutral'}>{i.status}</Badge>
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
      <div className="intg-detail intg-enter" key={i.id}>
        <div className="panel-head">
          <div className="row" style={{ gap: 10, minWidth: 0 }}>
            <span className={`intg-dot intg-dot--${h}`} aria-hidden="true" />
            <div>
              <div className="panel-title">{i.name}</div>
              <div className="muted">{i.provider}</div>
            </div>
          </div>
          <Badge tone={healthTone(h)}>{healthLabel(h)}</Badge>
        </div>

        {/* error state — connector unhealthy */}
        {i.status === 'error' && (
          <div className="intg-blocked intg-blocked--error" role="alert">
            <div className="intg-blocked-title">⚠ {L('Connector unhealthy', 'Միակցիչն անսարք է')}</div>
            <div className="muted">
              {L(
                'This connector reported an error on its last health check. Reconnect to run its check again, or provision it through the engine / operator.',
                'Այս միակցիչը վերջին ստուգման ժամանակ սխալ է հաղորդել։ Վերամիացրե՛ք ստուգումը կրկնելու համար, կամ տրամադրե՛ք այն շարժիչի/օպերատորի միջոցով։',
              )}
            </div>
            <div style={{ marginTop: 10 }}>
              <Button small variant="primary" disabled={busyId === i.id} onClick={() => setStatus(i, 'connected')}>
                {L('Reconnect', 'Վերամիացնել')}
              </Button>
            </div>
          </div>
        )}

        {/* per-connector config (real fields; the desktop holds no config schema/secret) */}
        <section aria-label={L('Configuration', 'Կարգավորում')}>
          <div className="intg-section-title">{L('Configuration', 'Կարգավորում')}</div>
          <div className="intg-fields">
            <Field label={L('Provider', 'Մատակարար')}>{i.provider}</Field>
            <Field label={L('Status', 'Կարգավիճակ')}>
              <Badge tone={statusTone[i.status] ?? 'neutral'}>{i.status}</Badge>
            </Field>
            <Field label={L('Health', 'Առողջություն')}>{healthLabel(h)}</Field>
            <Field label={L('Added', 'Ավելացված')}>
              {isNaN(created.getTime()) ? '—' : dateFmt.format(created)}
            </Field>
            <Field label={L('Last checked', 'Վերջին ստուգում')}>
              {isNaN(updated.getTime()) ? '—' : dateFmt.format(updated)}
            </Field>
          </div>
        </section>

        {/* auth handoff — clearly labeled; the desktop stores NO external secret */}
        <section aria-label={L('Authentication', 'Նույնականացում')}>
          <div className="intg-section-title">{L('Authentication', 'Նույնականացում')}</div>
          <div className="intg-auth">
            <Badge tone="info">{L('Handoff → engine / operator', 'Փոխանցում → շարժիչ/օպերատոր')}</Badge>
            <p className="muted" style={{ margin: '8px 0 0' }}>
              {L(
                'Secrets are held by the engine / operator — this desktop stores none. Connecting hands authentication off to the governed engine; no credential is persisted here.',
                'Գաղտնիքները պահվում են շարժիչի/օպերատորի կողմից — այս աշխատասեղանը ոչ մեկը չի պահում։ Միանալիս նույնականացումը փոխանցվում է կառավարվող շարժիչին. այստեղ ոչ մի հավատարմագիր չի պահվում։',
              )}
            </p>
          </div>
        </section>

        {/* inbound triggers + outbound sinks — no backing command exists yet, so
            the honest `blocked` state (not provisioned + how to provision). */}
        <section aria-label={L('Triggers & sinks', 'Հրահրիչներ և ընդունիչներ')}>
          <div className="intg-section-title">{L('Inbound triggers & outbound sinks', 'Մուտքային հրահրիչներ և ելքային ընդունիչներ')}</div>
          <div className="intg-blocked" role="note">
            <div className="intg-blocked-title">🔒 {L('Mapping not provisioned', 'Կապակցումը տրամադրված չէ')}</div>
            <div className="muted">
              {L(
                'Trigger and sink mapping is not provisioned on this desktop. It stays blocked so an inbound event can never start ungoverned work and a sink can only send verified results.',
                'Հրահրիչ–ընդունիչ կապակցումն այս աշխատասեղանում տրամադրված չէ։ Այն արգելափակված է մնում, որպեսզի մուտքային իրադարձությունը երբեք չմեկնարկի չկառավարվող աշխատանք, իսկ ընդունիչն ուղարկի միայն ստուգված արդյունքներ։',
              )}
            </div>
            <div className="intg-provision">
              <div className="field-label">{L('How to provision', 'Ինչպես տրամադրել')}</div>
              <ol className="intg-steps">
                <li>{L('Ask the operator to register the connector secret in the engine.', 'Խնդրե՛ք օպերատորին գրանցել միակցիչի գաղտնիքը շարժիչում։')}</li>
                <li>{L('Map inbound events to a governed task class (receipt required).', 'Կապե՛ք մուտքային իրադարձությունները կառավարվող առաջադրանքի դասին (անհրաժեշտ է անդորրագիր)։')}</li>
                <li>{L('Map an outbound sink that sends only verified results.', 'Կապե՛ք ելքային ընդունիչ, որն ուղարկում է միայն ստուգված արդյունքներ։')}</li>
              </ol>
            </div>
          </div>
        </section>

        {/* primary action (enable/disable) */}
        <div className="form-actions">
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
    <>
      <IntegrationsStyle />
      <PageHeader
        title={t('nav.integrations')}
        subtitle={t('integrations.subtitle')}
      />

      {/* live region: connect / disconnect / refusal announcements */}
      <div className="intg-live" role="status" aria-live="polite">
        {notice && (
          <div className={`intg-notice intg-notice--${notice.kind}`}>
            {notice.kind === 'blocked' && <span aria-hidden="true">🔒 </span>}
            {notice.kind === 'error' && <span aria-hidden="true">⚠ </span>}
            {notice.kind === 'blocked'
              ? `${L('Blocked', 'Արգելափակված')}: ${notice.text}`
              : notice.text}
          </div>
        )}
      </div>

      <div className="intg-layout">
        <Panel title={L('Connector catalog', 'Միակցիչների կատալոգ')}>
          <div className="intg-search">
            <input
              ref={searchRef}
              className="input"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={L('Search catalog  (/)', 'Փնտրել կատալոգը  (/)')}
              aria-label={L('Search connector catalog', 'Փնտրել միակցիչների կատալոգում')}
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
              title={L('No integrations', 'Ինտեգրումներ չկան')}
              hint={L('Connect a governed service to start.', 'Սկսելու համար միացրե՛ք կառավարվող ծառայություն։')}
            />
          ) : ordered.length === 0 ? (
            <EmptyState
              glyph="🔎"
              title={L('No matches', 'Համընկնումներ չկան')}
              hint={L('No connector matches your search.', 'Ձեր որոնմանը համապատասխան միակցիչ չկա։')}
            />
          ) : (
            <div className="stack">
              {connected.length > 0 && (
                <div>
                  <div className="intg-group-title">{L('Connected', 'Միացված')}</div>
                  <div role="list" aria-label={L('Connected connectors', 'Միացված միակցիչներ')} className="intg-list">
                    {connected.map((i) => renderRow(i, ordered.indexOf(i)))}
                  </div>
                </div>
              )}
              {available.length > 0 && (
                <div>
                  <div className="intg-group-title">{L('Available', 'Հասանելի')}</div>
                  <div role="list" aria-label={L('Available connectors', 'Հասանելի միակցիչներ')} className="intg-list">
                    {available.map((i) => renderRow(i, ordered.indexOf(i)))}
                  </div>
                </div>
              )}
              {!hasBackend() && (
                <div className="muted intg-hint">{t('state.offlineBanner')}</div>
              )}
            </div>
          )}
        </Panel>

        <div>
          {selected ? (
            <Panel>{renderDetail(selected)}</Panel>
          ) : (
            <Panel>
              <EmptyState
                glyph="🔌"
                title={L('Select a connector', 'Ընտրե՛ք միակցիչ')}
                hint={L(
                  'Choose a connector to view its configuration, health, authentication handoff, and trigger / sink mapping.',
                  'Ընտրե՛ք միակցիչ՝ դրա կարգավորումը, առողջությունը, նույնականացման փոխանցումը և հրահրիչ/ընդունիչ կապակցումը տեսնելու համար։',
                )}
              />
            </Panel>
          )}
        </div>
      </div>
    </>
  );
}

// Scoped styles for this page (kept inside the feature file per the build
// contract). Colors/spacing resolve through the shared design tokens; motion
// honours prefers-reduced-motion.
function IntegrationsStyle() {
  return (
    <style>{`
.intg-layout { display: grid; grid-template-columns: minmax(240px, 340px) 1fr; gap: var(--menq-space-4); align-items: start; }
@media (max-width: 860px) { .intg-layout { grid-template-columns: 1fr; } }

.intg-live { min-height: 0; }
.intg-notice { margin-bottom: var(--menq-space-4); padding: 9px 13px; border-radius: var(--menq-radius-md);
  font-size: 13px; border: 1px solid var(--brops-border); background: var(--menq-color-hover); color: var(--brops-text); }
.intg-notice--ok { border-color: color-mix(in srgb, var(--menq-color-success) 50%, transparent);
  background: color-mix(in srgb, var(--menq-color-success) 12%, transparent); }
.intg-notice--error { border-color: color-mix(in srgb, var(--menq-color-danger) 50%, transparent);
  background: color-mix(in srgb, var(--menq-color-danger) 12%, transparent); }
.intg-notice--blocked { border-color: color-mix(in srgb, var(--menq-color-warning) 50%, transparent);
  background: color-mix(in srgb, var(--menq-color-warning) 12%, transparent); }

.intg-search { margin-bottom: var(--menq-space-2); }

.intg-group-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--brops-muted); margin: var(--menq-space-2) 0 6px; }
.intg-list { display: flex; flex-direction: column; gap: 4px; }

.intg-row { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3);
  width: 100%; text-align: left; background: transparent; color: var(--brops-text); cursor: pointer;
  border: 1px solid transparent; border-radius: var(--menq-radius-md); padding: 9px 11px; font: inherit; }
.intg-row:hover { background: var(--menq-color-hover); }
.intg-row:focus-visible { outline: 2px solid var(--menq-color-focus); outline-offset: 1px; }
.intg-row--active { background: var(--menq-color-selected); border-color: var(--brops-accent); }
.intg-row-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.intg-row-provider { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }

.intg-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; background: var(--brops-muted); }
.intg-dot--healthy { background: var(--menq-color-success); box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 60%, transparent);
  animation: intg-pulse 2s infinite; }
.intg-dot--unhealthy { background: var(--menq-color-danger); }
.intg-dot--idle { background: var(--brops-muted); }

@keyframes intg-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 55%, transparent); }
  70% { box-shadow: 0 0 0 7px color-mix(in srgb, var(--menq-color-success) 0%, transparent); }
  100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 0%, transparent); }
}

.intg-detail { display: flex; flex-direction: column; gap: var(--menq-space-4); }
.intg-enter { animation: intg-enter var(--menq-motion-med) ease-out; }
@keyframes intg-enter { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

.intg-section-title { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.intg-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--menq-space-3); }
@media (max-width: 560px) { .intg-fields { grid-template-columns: 1fr; } }

.intg-auth { border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); padding: var(--menq-space-3); }

.intg-blocked { border: 1px dashed var(--brops-border); border-radius: var(--menq-radius-md);
  padding: var(--menq-space-4); background: var(--menq-color-hover); }
.intg-blocked--error { border-style: solid; border-color: color-mix(in srgb, var(--menq-color-danger) 45%, transparent);
  background: color-mix(in srgb, var(--menq-color-danger) 8%, transparent); }
.intg-blocked-title { font-weight: 600; margin-bottom: 6px; }
.intg-provision { margin-top: var(--menq-space-3); }
.intg-steps { margin: 6px 0 0; padding-left: 18px; color: var(--brops-muted); display: flex; flex-direction: column; gap: 4px; }

.intg-hint { font-size: 12px; margin-top: var(--menq-space-2); }

@media (prefers-reduced-motion: reduce) {
  .intg-dot--healthy { animation: none; }
  .intg-enter { animation: none; }
}
    `}</style>
  );
}
