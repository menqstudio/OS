import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import { Button, Skeleton, ErrorState, EmptyState, Field } from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { STR } from './Integrations.strings';
import {
  connectorStateOf, summarize, isGenuinelyConnected, UNTESTED,
  type ConnectorState, type Reachability, type Verdict,
} from './integrationsModel';
import {
  probeIntegration, declareIntegration, PROBE_COMMAND, DECLARE_COMMAND,
  type DeclareOutcome,
} from './integrationsProbe';

// ── What this page renders ────────────────────────────────────────────────────
// An integration here is a DECLARED external channel: a name + a provider in the
// desktop registry. It is not a credential (the desktop stores none) and not an open
// connection. So the page shows four separate facts per connector — declared, locally
// enabled, credential configured, actually reachable — and never collapses them into
// one green word. `integrationsModel.ts` owns the derivation and explains why.
//
// The only state that may paint a live affordance is `connected_verified`, which
// requires a reachability check that genuinely ran and genuinely answered.

/** aios health-token key (drives the --stc hue on the scoped `.st-*` classes).
 *  `live` is reserved for a verdict that a real check earned. */
function stKeyOf(v: Verdict): 'live' | 'error' | 'paused' {
  if (isGenuinelyConnected(v)) return 'live';
  return v === 'faulted' || v === 'unreachable' ? 'error' : 'paused';
}

/** aios pill variant. Same rule: only a verified verdict gets the `live` variant. */
function verdictPill(v: Verdict): string {
  if (isGenuinelyConnected(v)) return 'live';
  if (v === 'faulted' || v === 'unreachable') return 'warn cst-err';
  if (v === 'enabled_unverified') return 'info';
  return 'off';
}

/** A backend rejection that reads like a governance/secret refusal is surfaced as
 *  the spec's `blocked` state rather than a generic error. */
function isGovernanceBlock(message: string): boolean {
  return /secret|ungoverned|governance|not provisioned|auth|denied|permission|refus/i.test(message);
}

/** A probe result kept alongside the record version it was taken against. A check
 *  describes the record as it was; the moment the row is rewritten (enable, disable,
 *  a backend change) the old result is stale and this page falls back to `untested`
 *  rather than carrying a stale "verified" forward. */
interface ProbeEntry {
  reach: Reachability;
  recordVersion: string;
}

export function Integrations() {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const s = useAsync(() => desktop.listIntegrations(), []);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  // Live region text (aria-live=polite): the last enable/disable/declare/refusal.
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error' | 'blocked'; text: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [probes, setProbes] = useState<Record<string, ProbeEntry>>({});
  const [probingId, setProbingId] = useState<string | null>(null);
  // Set only once a REAL probe attempt came back as "this build cannot ask". Until
  // then the page makes no claim about its own capabilities either.
  const [probeUnsupported, setProbeUnsupported] = useState(false);

  const [declareOpen, setDeclareOpen] = useState(false);
  const [declareName, setDeclareName] = useState('');
  const [declareProvider, setDeclareProvider] = useState('');
  const [declaring, setDeclaring] = useState(false);
  const [declareBlock, setDeclareBlock] = useState<DeclareOutcome | null>(null);

  const searchRef = useRef<HTMLInputElement | null>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );

  const items = useMemo(() => s.data ?? [], [s.data]);

  // Every connector's derived state. `reachability` comes from a probe that really ran
  // against THIS version of the record — anything else is `untested`.
  const states = useMemo<ConnectorState[]>(
    () => items.map((i) => {
      const e = probes[i.id];
      const reach = e && e.recordVersion === i.updatedAt ? e.reach : UNTESTED;
      return connectorStateOf(i, reach);
    }),
    [items, probes],
  );

  // Telemetry — every count derived from the REAL array (never fabricated).
  const totals = useMemo(() => summarize(states), [states]);

  // Filter + partition. `enabled` holds what the owner switched on (including a
  // recorded fault, so a connector expected to work but broken stays visible there).
  const { enabledGroup, restGroup, ordered } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (c: ConnectorState) =>
      !q
      || c.record.name.toLowerCase().includes(q)
      || c.record.provider.toLowerCase().includes(q);
    const filtered = states.filter(match);
    const enabledGroup = filtered.filter((c) => c.enablement === 'enabled' || c.enablement === 'faulted');
    const restGroup = filtered.filter((c) => c.enablement === 'not_enabled' || c.enablement === 'unknown');
    return { enabledGroup, restGroup, ordered: [...enabledGroup, ...restGroup] };
  }, [states, query]);

  const selected = ordered.find((c) => c.record.id === selectedId)
    ?? states.find((c) => c.record.id === selectedId)
    ?? null;

  // ── Labels ──────────────────────────────────────────────────────────────────
  const verdictLabel = (v: Verdict) =>
    v === 'connected_verified' ? L('verdictConnectedVerified')
      : v === 'enabled_unverified' ? L('verdictEnabledUnverified')
        : v === 'unreachable' ? L('verdictUnreachable')
          : v === 'faulted' ? L('verdictFaulted')
            : v === 'not_enabled' ? L('verdictNotEnabled')
              : L('verdictUnknown');

  const verdictExplain = (v: Verdict) =>
    v === 'connected_verified' ? L('explainConnectedVerified')
      : v === 'enabled_unverified' ? L('explainEnabledUnverified')
        : v === 'unreachable' ? L('explainUnreachable')
          : v === 'faulted' ? L('explainFaulted')
            : v === 'not_enabled' ? L('explainNotEnabled')
              : L('explainUnknown');

  const enablementLabel = (c: ConnectorState) =>
    c.enablement === 'enabled' ? L('enablementEnabled')
      : c.enablement === 'not_enabled' ? L('enablementNotEnabled')
        : c.enablement === 'faulted' ? L('enablementFaulted')
          : L('enablementUnknown');

  const reachLabel = (r: Reachability) =>
    r.state === 'reachable' ? L('reachReachable')
      : r.state === 'unreachable' ? L('reachUnreachable')
        : r.state === 'indeterminate' ? L('reachIndeterminate')
          : r.state === 'unsupported' ? L('reachUnsupported')
            : L('reachUntested');

  const reachNote = (r: Reachability) =>
    r.state === 'untested' ? L('reachUntestedNote')
      : r.state === 'unsupported' ? L('reachUnsupportedNote').replace('{cmd}', PROBE_COMMAND)
        : r.state === 'indeterminate' ? L('reachIndeterminateNote')
          : null;

  const fmtDate = (raw: string) => {
    const d = new Date(raw);
    return isNaN(d.getTime()) ? '—' : dateFmt.format(d);
  };

  // ── Enable / disable (Space) ────────────────────────────────────────────────
  // This writes ONLY the local record. It contacts nothing, so it can never move a
  // connector into a verified state — and the copy on the button says so.
  const setStatus = (c: ConnectorState, status: 'connected' | 'disconnected') => {
    const i = c.record;
    setBusyId(i.id);
    setNotice(null);
    desktop.setIntegrationStatus(i.id, status)
      .then(() => {
        setBusyId(null);
        setNotice({
          kind: 'ok',
          text: (status === 'connected' ? L('enabledNamed') : L('disabledNamed'))
            .replace('{name}', i.name),
        });
        s.reload();
      })
      .catch((e: unknown) => {
        setBusyId(null);
        const msg = e instanceof Error ? e.message : String(e);
        // A refusal to enable (would hold a desktop secret / run ungoverned) is the
        // spec's `blocked` outcome, announced with its reason.
        setNotice({
          kind: status === 'connected' && isGovernanceBlock(msg) ? 'blocked' : 'error',
          text: msg,
        });
        s.reload();
      });
  };

  const toggle = (c: ConnectorState) =>
    setStatus(c, c.enablement === 'enabled' ? 'disconnected' : 'connected');

  // ── Reachability check ──────────────────────────────────────────────────────
  // Always user-initiated; never runs on mount. `probeIntegration` cannot throw and
  // cannot return `reachable` unless the backend really said so.
  const runProbe = (c: ConnectorState) => {
    const i = c.record;
    setProbingId(i.id);
    setNotice(null);
    probeIntegration(i.id).then((reach) => {
      setProbingId(null);
      if (reach.state === 'unsupported') setProbeUnsupported(true);
      setProbes((p) => ({ ...p, [i.id]: { reach, recordVersion: i.updatedAt } }));
    });
  };

  // ── Declare a connector ─────────────────────────────────────────────────────
  const submitDeclare = () => {
    setDeclaring(true);
    setDeclareBlock(null);
    setNotice(null);
    declareIntegration(declareName, declareProvider).then((outcome) => {
      setDeclaring(false);
      if (outcome.ok) {
        setNotice({ kind: 'ok', text: L('declaredNamed').replace('{name}', outcome.integration.name) });
        setDeclareOpen(false);
        setDeclareName('');
        setDeclareProvider('');
        setSelectedId(outcome.integration.id);
        s.reload();
        return;
      }
      if (outcome.kind === 'unsupported') {
        // A real capability refusal — report it as a missing feature here, with the
        // exact command that is missing, not as anything the connector did.
        setDeclareBlock(outcome);
        return;
      }
      setNotice({ kind: outcome.kind === 'refused' ? 'blocked' : 'error', text: outcome.reason });
    });
  };

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
  const onRowKeyDown = (e: KeyboardEvent<HTMLButtonElement>, idx: number, c: ConnectorState) => {
    if (e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault();
      if (busyId !== c.record.id) toggle(c);
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

  const renderRow = (c: ConnectorState, idx: number) => {
    const i = c.record;
    const active = i.id === selectedId;
    // Verdict AND reachability folded into the accessible name, so a screen reader
    // hears "unverified" exactly where a sighted user sees the pill (a11y requirement).
    const aria = `${i.name}, ${i.provider}, ${verdictLabel(c.verdict)}, ${reachLabel(c.reachability)}`;
    return (
      <div role="listitem" key={i.id}>
        <button
          type="button"
          ref={(el) => { rowRefs.current[idx] = el; }}
          className={`creg-row ${active ? 'is-sel' : ''}`}
          aria-label={aria}
          aria-current={active ? 'true' : undefined}
          onClick={() => { setSelectedId(i.id); setNotice(null); }}
          onKeyDown={(e) => onRowKeyDown(e, idx, c)}
        >
          <span className={`cr-dot st-${stKeyOf(c.verdict)}`} aria-hidden="true" />
          <span className="cr-main">
            <b>{i.name}</b>
            <span className="micro">{i.provider}</span>
          </span>
          <span className={`pill ${verdictPill(c.verdict)}`}>{verdictLabel(c.verdict)}</span>
        </button>
      </div>
    );
  };

  // ── One row of the four-fact ledger ─────────────────────────────────────────
  const ledgerRow = (label: string, value: string, tone: string, note?: string | null) => (
    <div className="intg-fact">
      <dt className="intg-fact-k">{label}</dt>
      <dd className="intg-fact-v">
        <span className={`pill ${tone}`}>{value}</span>
        {note && <p className="micro intg-fact-note">{note}</p>}
      </dd>
    </div>
  );

  // ── Detail pane for the selected connector ──────────────────────────────────
  const renderDetail = (c: ConnectorState) => {
    const i = c.record;
    const r = c.reachability;
    const probing = probingId === i.id;
    return (
      <div className="cst-detail rise" key={i.id}>
        <div className="cd-head">
          <span className={`cd-badge st-${stKeyOf(c.verdict)}`} aria-hidden="true" />
          <div className="cd-id">
            <span className="eyebrow">{i.provider} · {L('channel')}</span>
            <b>{i.name}</b>
          </div>
          <span className={`pill ${verdictPill(c.verdict)}`}>{verdictLabel(c.verdict)}</span>
        </div>
        <p className="micro intg-verdict-note">{verdictExplain(c.verdict)}</p>

        {/* recorded fault */}
        {c.enablement === 'faulted' && (
          <div className="intg-blocked intg-blocked--error" role="alert">
            <div className="intg-blocked-title">⚠ {L('connectorUnhealthy')}</div>
            <div className="micro">{L('connectorUnhealthyBody')}</div>
            <div style={{ marginTop: 10 }}>
              <Button small variant="primary" disabled={busyId === i.id} onClick={() => setStatus(c, 'connected')}>
                {L('reconnect')}
              </Button>
            </div>
          </div>
        )}

        {/* ── the four facts, each allowed to say "unknown" ─────────────────── */}
        <section aria-label={L('ledgerTitle')}>
          <div className="intg-section-title">{L('ledgerTitle')}</div>
          <dl className="intg-facts">
            {ledgerRow(L('factDeclaration'), L('factDeclarationValue'), 'info', L('factDeclarationNote'))}
            {ledgerRow(
              L('factEnablement'),
              enablementLabel(c),
              c.enablement === 'enabled' ? 'info' : c.enablement === 'faulted' ? 'warn cst-err' : 'off',
              L('factEnablementNote'),
            )}
            {ledgerRow(
              L('factCredential'),
              c.credential === 'referenced' ? L('credentialReferenced') : L('credentialNoReference'),
              c.credential === 'referenced' ? 'info' : 'off',
              c.credential === 'referenced' ? L('credentialReferencedNote') : L('credentialNoReferenceNote'),
            )}
            {ledgerRow(
              L('factReachability'),
              reachLabel(r),
              r.state === 'reachable' ? 'live' : r.state === 'unreachable' ? 'warn cst-err' : 'off',
              reachNote(r),
            )}
          </dl>
        </section>

        {/* ── reachability check ────────────────────────────────────────────── */}
        <section aria-label={L('testReachability')}>
          <div className="intg-section-title">{L('factReachability')}</div>
          <div className="intg-probe">
            <div className="intg-probe-actions">
              <Button small disabled={probing} onClick={() => runProbe(c)}>
                {probing ? L('testing') : L('testReachability')}
              </Button>
              {r.checkedAt && (
                <span className="micro">{L('lastAttempt')}: {fmtDate(r.checkedAt)}</span>
              )}
            </div>
            <p className="micro intg-probe-note">{L('testNote')}</p>
            {/* The verbatim backend reason. Never paraphrased into a friendlier
                outcome than the one that actually came back. */}
            {r.reason && (
              <p className="micro intg-probe-reason" role="status">
                <b>{L('probeReason')}:</b> <code>{r.reason}</code>
              </p>
            )}
          </div>
        </section>

        {/* auth handoff — clearly labeled; the desktop stores NO external secret */}
        <section aria-label={L('authentication')}>
          <div className="intg-section-title">{L('authentication')}</div>
          <div className="intg-auth">
            <span className="pill info">{L('handoff')}</span>
            <p className="micro" style={{ margin: '8px 0 0' }}>{L('authBody')}</p>
          </div>
        </section>

        {/* the raw record, so the derived facts above can always be checked */}
        <section aria-label={L('configuration')}>
          <div className="intg-section-title">{L('configuration')}</div>
          <div className="intg-fields">
            <Field label={L('provider')}>{i.provider}</Field>
            <Field label={L('recordStatus')}><code>{i.status}</code></Field>
            <Field label={L('added')}>{fmtDate(i.createdAt)}</Field>
            <Field label={L('recordUpdated')}>{fmtDate(i.updatedAt)}</Field>
          </div>
        </section>

        {/* inbound triggers + outbound sinks — no backing command exists yet, so
            the honest `blocked` state (not provisioned + how to provision). */}
        <section aria-label={L('triggersSinks')}>
          <div className="intg-section-title">{L('triggersSinksTitle')}</div>
          <div className="intg-blocked" role="note">
            <div className="intg-blocked-title">🔒 {L('mappingNotProvisioned')}</div>
            <div className="micro">{L('mappingBody')}</div>
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

        {/* primary action — local record only, and it says so */}
        <div className="cd-foot">
          {c.enablement === 'enabled' ? (
            <Button variant="ghost" disabled={busyId === i.id} onClick={() => setStatus(c, 'disconnected')}>
              {L('disableAction')}
            </Button>
          ) : (
            <Button variant="primary" disabled={busyId === i.id} onClick={() => setStatus(c, 'connected')}>
              {L('enableAction')}
            </Button>
          )}
          <p className="micro intg-action-note">
            {L('enableActionNote').replace('{name}', i.provider)}
          </p>
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
            <>
              {/* Two separate claims, because they are two separate facts. */}
              <span className={`pill ${totals.anyVerifiedConnected ? 'live' : 'off'}`}>
                {L('headerVerified').replace('{n}', String(totals.verifiedConnected))}
              </span>
              <span className={`pill ${totals.enabled > 0 ? 'info' : 'off'}`}>
                {L('headerEnabled').replace('{n}', String(totals.enabled))}
              </span>
            </>
          )}
          {/* The live mark is earned only by a connector a real check confirmed. */}
          <Mark state={totals.anyVerifiedConnected ? 'live' : 'idle'} size={30} />
        </div>
      </header>

      {/* live region: enable / disable / declare / refusal announcements */}
      <div className="intg-live" role="status" aria-live="polite">
        {notice && (
          <div className={`intg-notice intg-notice--${notice.kind}`}>
            {notice.kind === 'blocked' && <span aria-hidden="true">🔒 </span>}
            {notice.kind === 'error' && <span aria-hidden="true">⚠ </span>}
            {notice.kind === 'blocked' ? `${L('blocked')}: ${notice.text}` : notice.text}
          </div>
        )}
      </div>

      {/* Shown only after a REAL probe attempt came back "this build cannot ask".
          Before that the page asserts nothing about its own capabilities. */}
      {probeUnsupported && (
        <div className="intg-blocked intg-cap" role="note">
          <div className="intg-blocked-title">🔒 {L('capTitle')}</div>
          <div className="micro">{L('capBody').replace('{probe}', PROBE_COMMAND)}</div>
        </div>
      )}

      {/* ── HERO · real-derived telemetry band ─────────────────────────────── */}
      {!loading && !s.error && totals.total > 0 && (
        <section className="surface soft lg hud intg-hero" aria-label={L('integrationOverview')}>
          <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
          <div className="intg-stats">
            <span className="capsule"><b>{totals.total}</b><span>{L('statDeclared')}</span></span>
            <span className="capsule"><b>{totals.enabled}</b><span>{L('statEnabled')}</span></span>
            <span className={`capsule ${totals.verifiedConnected > 0 ? 'is-ok' : ''}`}>
              <b>{totals.verifiedConnected}</b><span>{L('statVerified')}</span>
            </span>
            <span className={`capsule ${totals.faulted > 0 ? 'is-warn' : ''}`}>
              <b>{totals.faulted}</b><span>{L('statFaulted')}</span>
            </span>
            <span className="capsule"><b>{totals.untested}</b><span>{L('statUntested')}</span></span>
          </div>
          {/* The travelling `live` pulse is earned only when a check really confirmed
              a channel; with nothing verified it is a still divider, not a feed. */}
          <div className={`wire${totals.anyVerifiedConnected ? ' live' : ''}`} aria-hidden="true" />
          <p className="micro intg-scale">{L('stateScale')}</p>
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

          {/* ── declare a connector (a name, never a credential) ────────────── */}
          <div className="intg-declare">
            {!declareOpen ? (
              <Button small onClick={() => { setDeclareOpen(true); setDeclareBlock(null); }}>
                {L('declareOpen')}
              </Button>
            ) : (
              <form
                className="intg-declare-form"
                aria-label={L('declareTitle')}
                onSubmit={(e) => { e.preventDefault(); submitDeclare(); }}
              >
                <div className="intg-section-title">{L('declareTitle')}</div>
                <p className="micro">{L('declareBody')}</p>
                <label className="intg-lab">
                  <span className="eyebrow">{L('declareName')}</span>
                  <input
                    className="input"
                    value={declareName}
                    onChange={(e) => setDeclareName(e.target.value)}
                    placeholder={L('declareNamePlaceholder')}
                  />
                </label>
                <label className="intg-lab">
                  <span className="eyebrow">{L('declareProvider')}</span>
                  <input
                    className="input"
                    value={declareProvider}
                    onChange={(e) => setDeclareProvider(e.target.value)}
                    placeholder={L('declareProviderPlaceholder')}
                  />
                </label>
                <div className="intg-declare-actions">
                  <Button small variant="primary" type="submit" disabled={declaring}>
                    {declaring ? L('declaring') : L('declareSubmit')}
                  </Button>
                  <Button small variant="ghost" onClick={() => { setDeclareOpen(false); setDeclareBlock(null); }}>
                    {L('declareCancel')}
                  </Button>
                </div>
                {/* The refusal, with the exact missing command — not a vague failure. */}
                {declareBlock && !declareBlock.ok && (
                  <div className="intg-blocked" role="alert">
                    <div className="intg-blocked-title">
                      🔒 {declareBlock.kind === 'unsupported' ? L('declareUnsupported') : L('declareRefused')}
                    </div>
                    <div className="micro">
                      {declareBlock.kind === 'unsupported'
                        ? L('declareUnsupportedBody').replace('{cmd}', DECLARE_COMMAND)
                        : declareBlock.reason}
                    </div>
                    {declareBlock.kind === 'unsupported' && (
                      <p className="micro intg-probe-reason"><code>{declareBlock.reason}</code></p>
                    )}
                  </div>
                )}
              </form>
            )}
          </div>

          {loading ? (
            <Skeleton rows={5} />
          ) : s.error ? (
            <ErrorState message={s.error} onRetry={s.reload} />
          ) : totals.total === 0 ? (
            <EmptyState glyph="🔌" title={L('noIntegrations')} hint={L('noIntegrationsHint')} />
          ) : ordered.length === 0 ? (
            <EmptyState glyph="🔎" title={L('noMatches')} hint={L('noMatchesHint')} />
          ) : (
            <div className="creg">
              {enabledGroup.length > 0 && (
                <div className="creg-group">
                  <div className="creg-head"><span className="creg-gname">{L('groupEnabled')}</span></div>
                  <div role="list" aria-label={L('enabledConnectors')} className="intg-list">
                    {enabledGroup.map((c) => renderRow(c, ordered.indexOf(c)))}
                  </div>
                </div>
              )}
              {restGroup.length > 0 && (
                <div className="creg-group">
                  <div className="creg-head"><span className="creg-gname">{L('groupNotEnabled')}</span></div>
                  <div role="list" aria-label={L('notEnabledConnectors')} className="intg-list">
                    {restGroup.map((c) => renderRow(c, ordered.indexOf(c)))}
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
.v-integrations .intg-stats .capsule.is-ok { color:var(--success);
  border-color:rgb(var(--success-rgb)/.3); background:rgb(var(--success-rgb)/.08); }
.v-integrations .intg-stats .capsule.is-ok b { color:var(--success); }
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

.v-integrations .intg-cap { margin-bottom:var(--s5); }

.v-integrations .intg-search { margin:var(--s3) 0 var(--s3); }
.v-integrations .intg-declare { margin-bottom:var(--s4); }
.v-integrations .intg-declare-form { display:flex; flex-direction:column; gap:var(--s3);
  border:1px solid rgb(var(--line-rgb)/.8); border-radius:var(--r); padding:var(--s4); }
.v-integrations .intg-lab { display:flex; flex-direction:column; gap:4px; }
.v-integrations .intg-declare-actions { display:flex; gap:8px; flex-wrap:wrap; }

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
.v-integrations .intg-verdict-note { color:var(--ink-muted); margin:calc(-1 * var(--s3)) 0 0; }

.v-integrations .intg-section-title { font-weight:600; font-size:var(--t-small); margin-bottom:8px; }
.v-integrations .intg-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--s3); }
@media (max-width:560px){ .v-integrations .intg-fields { grid-template-columns:1fr; } }

.v-integrations .intg-facts { display:flex; flex-direction:column; gap:var(--s3); margin:0;
  border:1px solid rgb(var(--line-rgb)/.8); border-radius:var(--r); padding:var(--s4); }
.v-integrations .intg-fact { display:grid; grid-template-columns:minmax(120px,150px) 1fr; gap:var(--s3);
  align-items:start; }
@media (max-width:560px){ .v-integrations .intg-fact { grid-template-columns:1fr; gap:4px; } }
.v-integrations .intg-fact-k { font-size:var(--t-small); color:var(--ink-muted); margin:0; }
.v-integrations .intg-fact-v { margin:0; min-width:0; }
.v-integrations .intg-fact-note { color:var(--ink-muted); margin:6px 0 0; }

.v-integrations .intg-probe { border:1px solid rgb(var(--line-rgb)/.8); border-radius:var(--r); padding:var(--s4); }
.v-integrations .intg-probe-actions { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.v-integrations .intg-probe-actions .micro { color:var(--ink-muted); }
.v-integrations .intg-probe-note { color:var(--ink-muted); margin:8px 0 0; }
.v-integrations .intg-probe-reason { margin:8px 0 0; word-break:break-word; }
.v-integrations .intg-probe-reason code { font-family:var(--f-mono); font-size:var(--t-micro); }

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

.v-integrations .cd-foot { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
.v-integrations .intg-action-note { color:var(--ink-muted); margin:0; flex:1 1 240px; }
.v-integrations .intg-hint { color:var(--ink-muted); margin-top:var(--s3); }

@media (prefers-reduced-motion:reduce){ .v-integrations .cr-dot.st-live { animation:none; } }
    `}</style>
  );
}
