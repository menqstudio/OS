import { useRef, type ReactNode, type KeyboardEvent, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { Skeleton, ErrorState, EmptyState } from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Mark } from '../components/Ambient';
import { TrustSelftestPanel } from '../components/TrustSelftest';

// ⛨ Անվտանգություն — Evidence chain / posture (Phase-2 §D), re-dressed into the
// AI-OS design language (aios.css) as a "manifest instrument" + posture strip.
//
// Data honesty is UNCHANGED. The ONLY backing command that exists today is
// `get_security_summary` (posture counts + recent sensitive ActivityEvents),
// which drives the real posture strip and the sensitive-events section. The four
// engine-truth components (chain-integrity, control-plane digest, residual
// tracker O-1..O-5, key/lease registry) read from the engine evidence chain, for
// which NO read-only IPC command is wired into the desktop yet. Rather than
// fabricate a "verified" chain or fake digests/leases, each renders its honest
// `blocked` state. The instrument NEVER shows a confident SECURE/verified posture
// or a live/green mark: the core power-mark and posture pill are driven straight
// from the real load state — idle/alert/blocked — never forced live.

/** Derived integrity of the evidence chain, from the real load state only.
 *  `verified` is intentionally NOT a value: the desktop has no chain-read
 *  command, so it never claims a good chain — steady state is `blocked`. */
type Integrity = 'checking' | 'broken' | 'blocked';

// Sections in tab order. Digit shortcuts (1..N) + `[` / `]` move focus between
// them, satisfying the spec's "sectioned tab order".
const SECTION_COUNT = 6;

// Honest posture → chrome. Never `.pill.live` (green) and never a live/on mark:
// trust is unproven, so the strongest states we express are info/warn + idle/alert.
const PILL_BY_INTEGRITY: Record<Integrity, 'info' | 'warn'> = {
  checking: 'info',
  broken: 'warn',
  blocked: 'warn',
};
const MARK_BY_INTEGRITY: Record<Integrity, string> = {
  checking: 'boot',
  broken: 'alert',
  blocked: 'idle',
};

/** One residual/deferred engine security item (roadmap §K, O-1..O-5). The
 *  desktop has no live status feed for these, so each renders "unverified". */
interface Residual {
  id: string;
  en: string;
  hy: string;
}

const RESIDUALS: Residual[] = [
  { id: 'O-1', en: 'Bytecode-shadow', hy: 'Բայթկոդի ստվեր' },
  { id: 'O-2', en: 'Audit-head anchor', hy: 'Աուդիտի գլխի խարիսխ' },
  { id: 'O-3', en: 'Conductor session token', hy: 'Դիրիժորի սեսիայի թոքեն' },
  { id: 'O-4', en: 'Control-room actor', hy: 'Կառավարման սենյակի դերակատար' },
  { id: 'O-5', en: 'Evidence high-water', hy: 'Ապացույցի վերին սահման' },
];

const cv = (i: number): CSSProperties => ({ ['--i']: i } as CSSProperties);

/** HUD corner brackets + edge ticks — purely decorative chrome. */
function HudChrome() {
  return (
    <>
      <span className="bracket tl" aria-hidden="true" />
      <span className="bracket tr" aria-hidden="true" />
      <span className="bracket bl" aria-hidden="true" />
      <span className="bracket br" aria-hidden="true" />
    </>
  );
}

export function Security() {
  const { t, lang } = useApp();
  const s = useAsync(() => desktop.getSecuritySummary(), []);
  // Real, READ-ONLY engine evidence-chain read — the honest source for the
  // chain-integrity view and the control-plane digest. In Phase-2 it is
  // blocked/unreachable (the engine chain read is not answering yet); the desktop
  // never claims a "verified" chain of its own — it mirrors, it does not adjudicate.
  const chain = useAsync(() => desktop.readEvidenceChain(), []);
  const tr = (en: string, hy: string) => (lang === 'hy' ? hy : en);

  const backend = hasBackend();
  // Honest derivation from the real chain read — never a fabricated "verified".
  // `checking` while the read is in flight; otherwise `blocked` (the engine
  // adjudicates integrity; the desktop only mirrors, and today the read is sealed).
  const integrity: Integrity =
    chain.data === null && chain.loading ? 'checking'
      : (chain.error || (chain.data && chain.data.state === 'unreachable')) && backend ? 'broken'
        : 'blocked';
  // The honest machine reason from the engine, surfaced verbatim where we have one.
  const chainReason = chain.data && chain.data.state !== 'ok' ? chain.data.reason : undefined;

  // --- Sectioned tab order: refs + keyboard navigation -------------------------------
  const sectionRefs = useRef<Array<HTMLElement | null>>([]);
  const focusSection = (i: number) => {
    const el = sectionRefs.current[i];
    if (el) el.focus();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (e.key >= '1' && e.key <= String(SECTION_COUNT)) {
      const idx = Number(e.key) - 1;
      if (sectionRefs.current[idx]) {
        e.preventDefault();
        focusSection(idx);
      }
      return;
    }
    if (e.key === ']' || e.key === '[') {
      e.preventDefault();
      const cur = sectionRefs.current.findIndex((el) => el === document.activeElement);
      const from = cur === -1 ? (e.key === ']' ? -1 : SECTION_COUNT) : cur;
      const next = e.key === ']'
        ? Math.min(from + 1, SECTION_COUNT - 1)
        : Math.max(from - 1, 0);
      focusSection(next);
    }
  };

  // --- One section = a labelled, focusable instrument card ----------------------------
  const section = (index: number, id: string, title: string, hint: string | null, body: ReactNode) => (
    <section
      key={id}
      ref={(el) => { sectionRefs.current[index] = el; }}
      role="region"
      aria-labelledby={`${id}-h`}
      tabIndex={0}
      className="sec-section surface soft reveal"
      style={cv(index + 1)}
    >
      <div className="sec-head">
        <h2 id={`${id}-h`}>{title}</h2>
        <span className="sec-idx" aria-hidden="true">{index + 1}</span>
      </div>
      {hint && <p className="sec-hint micro">{hint}</p>}
      {body}
    </section>
  );

  // Honest "no read command wired" notice reused by every engine-truth section.
  const blockedNote = (extraEn: string, extraHy: string) => (
    <div className="sec-blocked" role="note">
      <span className="pill warn">{tr('Blocked', 'Արգելափակված')}</span>
      <span className="note">{tr(extraEn, extraHy)}</span>
    </div>
  );

  // --- Honest posture labels (live region text) --------------------------------------
  const integrityLabel = integrity === 'checking'
    ? tr('Verifying…', 'Ստուգվում է…')
    : integrity === 'broken'
      ? tr('Chain read failed', 'Շղթայի ընթերցումը ձախողվեց')
      : tr('Integrity unverified', 'Ամբողջականությունը չհաստատված');
  const integrityDetail = integrity === 'checking'
    ? tr('Reading the evidence chain…', 'Կարդում ենք ապացույցների շղթան…')
    : integrity === 'broken'
      ? tr(
        'The evidence-chain read failed — the desktop cannot confirm integrity. The engine adjudicates; retry the read in the posture section below.',
        'Ապացույցների շղթայի ընթերցումը ձախողվեց — աշխատասեղանը չի կարող հաստատել ամբողջականությունը։ Շարժիչը որոշում է. կրկնեք ընթերցումը ստորև։',
      )
      : tr(
        'Chain integrity is adjudicated by the engine (Ed25519). The read-only evidence-chain command is not wired into the desktop yet, so integrity cannot be confirmed here.',
        'Շղթայի ամբողջականությունը որոշում է շարժիչը (Ed25519)։ Միայն-ընթերցման ապացույցների շղթայի հրամանը դեռ միացված չէ աշխատասեղանին, ուստի ամբողջականությունն այստեղ չի հաստատվում։',
      );

  // --- 0 · THE MANIFEST · chain-integrity instrument (REAL chain read, live region) --
  const integrityHero = (
    <section
      ref={(el) => { sectionRefs.current[0] = el; }}
      role="region"
      aria-labelledby="sec-integrity-h"
      tabIndex={0}
      className={`sec-section mani surface soft lg hud reveal sec-int--${integrity}`}
      style={cv(1)}
    >
      <HudChrome />
      <div className="mani-head">
        <div className="mh-title">
          <h2 className="eyebrow" id="sec-integrity-h">
            {tr('Evidence-chain integrity', 'Ապացույցների շղթայի ամբողջականություն')}
          </h2>
          <span className="mh-sub micro">{tr('Adjudicated by the engine · Ed25519', 'Որոշում է շարժիչը · Ed25519')}</span>
        </div>
        <span className="sec-idx" aria-hidden="true">1</span>
      </div>

      <div className="mani-core">
        <span className="mc-mark" aria-hidden="true">
          <span className="mc-halo" />
          <Mark state={MARK_BY_INTEGRITY[integrity]} size={64} />
        </span>
        <div
          className="mc-read"
          role="status"
          aria-live={integrity === 'broken' ? 'assertive' : 'polite'}
        >
          <span className={`pill ${PILL_BY_INTEGRITY[integrity]}`}>{integrityLabel}</span>
          <p className="mc-detail">{integrityDetail}</p>
          {chainReason ? (
            <p className="mc-reason micro">{tr('Engine reason: ', 'Շարժիչի պատճառ՝ ')}{chainReason}</p>
          ) : null}
        </div>
      </div>

      {/* Non-live wire: the chain does not flow — nothing is confirmed. */}
      <div className="wire" />
      {/* Honest link chain: the three engine-truth surfaces, NONE confirmed
          (no `.done`/`.now`) — mirroring the blocked posture, not implying trust. */}
      <div className="chain" aria-label={tr('Engine surfaces — none confirmed', 'Շարժիչի մակերեսներ — չհաստատված')}>
        <b>{tr('DIGEST', 'DIGEST')}</b>
        <b>{tr('CHAIN', 'ՇՂԹԱ')}</b>
        <b>{tr('LEASES', 'ՎԱՐՁ.')}</b>
        <span className="micro chain-note">{tr('unverified', 'չհաստատված')}</span>
      </div>
    </section>
  );

  // --- 1 · POSTURE STRIP (REAL data: get_security_summary) ---------------------------
  const postureStrip = (
    <section
      ref={(el) => { sectionRefs.current[1] = el; }}
      role="region"
      aria-labelledby="sec-posture-h"
      tabIndex={0}
      className="sec-section astats-wrap surface soft reveal"
      style={cv(2)}
    >
      <div className="sec-head">
        <h2 id="sec-posture-h">{t('nav.security')}</h2>
        <span className="sec-idx" aria-hidden="true">2</span>
      </div>
      <p className="sec-hint micro">
        {tr('Live posture counts from the engine audit summary.', 'Կենդանի ցուցանիշներ շարժիչի աուդիտի ամփոփումից։')}
      </p>
      {s.loading && s.data === null ? (
        <Skeleton rows={3} />
      ) : s.error ? (
        // ErrorState already renders the calm offline state when there is no backend.
        <ErrorState message={s.error} onRetry={s.reload} />
      ) : s.data ? (
        <div className="astats">
          <div className="astat as-warn">
            <b className="mono">{s.data.pendingApprovals}</b>
            <span className="micro">{t('security.pending')}</span>
          </div>
          <div className="astat as-info">
            <b className="mono">{s.data.decidedApprovals}</b>
            <span className="micro">{t('security.decided')}</span>
          </div>
          <div className="astat as-info">
            <b className="mono">{s.data.auditEvents}</b>
            <span className="micro">{t('security.audit')}</span>
          </div>
        </div>
      ) : null}
      <div className="wire" />
    </section>
  );

  // --- 2 · Protected control-plane digest (blocked: no read command) -----------------
  const digestSection = section(
    2,
    'sec-digest',
    tr('Control-plane digest', 'Կառավարման հարթության ամփոփ (digest)'),
    tr('Read-only protected-control-plane digest.', 'Միայն-ընթերցման պաշտպանված կառավարման հարթության digest։'),
    <>
      <div className="sec-digest-row">
        <span className="micro">SHA-256</span>
        <code className="sec-digest-val mono">—</code>
      </div>
      {blockedNote(
        'The protected control-plane digest is held by the engine and mirrored read-only; the engine chain read is not answering yet, so no digest is shown (never a fabricated one).',
        'Պաշտպանված կառավարման հարթության digest-ը պահվում է շարժիչում և արտացոլվում է միայն ընթերցմամբ. շարժիչի շղթայի ընթերցումը դեռ չի պատասխանում, ուստի digest ցույց չի տրվում (երբեք կեղծ)։',
      )}
      {chainReason ? (
        <p className="note sec-reason micro">{tr('Engine reason: ', 'Շարժիչի պատճառ՝ ')}{chainReason}</p>
      ) : null}
    </>,
  );

  // --- 3 · Residual-item tracker O-1..O-5 (blocked: no live feed) ---------------------
  const residualSection = section(
    3,
    'sec-residual',
    tr('Residual items (O-1..O-5)', 'Մնացորդային կետեր (O-1..O-5)'),
    tr('Deferred engine security items; each closed by its own audited task.', 'Հետաձգված շարժիչի անվտանգության կետեր. յուրաքանչյուրը փակվում է առանձին աուդիտով։'),
    <ul className="sec-residual-list" role="list">
      {RESIDUALS.map((r) => (
        <li key={r.id} className="sec-residual-item" role="listitem">
          <span className="sec-residual-lead">
            <span className="tag">{r.id}</span>
            <span className="sec-residual-name">{tr(r.en, r.hy)}</span>
          </span>
          <span className="pill warn">{tr('Unverified', 'Չհաստատված')}</span>
        </li>
      ))}
    </ul>,
  );

  // --- 4 · Key & lease registry (blocked by design: desktop caches nothing) ----------
  const registrySection = section(
    4,
    'sec-registry',
    tr('Key & lease registry', 'Բանալիների և վարձակալությունների ռեեստր'),
    tr('Ownership held by the engine Ed25519 system.', 'Սեփականությունը պահվում է շարժիչի Ed25519 համակարգում։'),
    blockedNote(
      'By design the desktop caches no keys or leases; the registry lives in the engine and no read command is wired here.',
      'Ըստ նախագծման աշխատասեղանը չի պահում բանալիներ կամ վարձակալություններ. ռեեստրը շարժիչում է, ընթերցման հրաման այստեղ միացված չէ։',
    ),
  );

  // --- 5 · Recent sensitive events (REAL data) ---------------------------------------
  const sensitiveSection = section(
    5,
    'sec-sensitive',
    t('security.sensitive'),
    null,
    s.loading && s.data === null ? (
      <Skeleton rows={3} />
    ) : s.error ? (
      <ErrorState message={s.error} onRetry={s.reload} />
    ) : !s.data || s.data.sensitiveEvents.length === 0 ? (
      <EmptyState title={t('state.empty')} />
    ) : (
      <div className="sec-events">
        {s.data.sensitiveEvents.map((ev) => (
          <div key={ev.id} className="sec-event">
            <span className="se-lead">
              <span className="tag">{ev.eventType}</span>
              <span className="note">
                {ev.entityType ?? '—'}{ev.entityId ? ` · ${ev.entityId}` : ''}
              </span>
            </span>
            <span className="note se-time mono">{ev.createdAt}</span>
          </div>
        ))}
      </div>
    ),
  );

  return (
    <>
      <style>{SEC_STYLE}</style>
      <div className="v-security sec-page" onKeyDown={onKeyDown}>
        <header className="pageHead reveal" style={cv(0)}>
          <div>
            <span className="eyebrow">{tr('TRUST & DEFENSE CORE', 'ՎՍՏԱՀՈՒԹՅԱՆ ՄԻՋՈՒԿ')}</span>
            <h1>{t('nav.security')}</h1>
            <p className="sub">{t('security.subtitle')}</p>
          </div>
          <div className="right">
            <Mark state={MARK_BY_INTEGRITY[integrity]} size={22} />
            <span className={`pill ${PILL_BY_INTEGRITY[integrity]}`}>{integrityLabel}</span>
          </div>
        </header>

        <p className="sec-nav-hint micro">
          {tr('Press 1–6, or [ and ] to move between sections.', 'Սեղմեք 1–6, կամ [ և ] բաժինների միջև տեղափոխվելու համար։')}
        </p>

        <div className="sec-sections">
          {integrityHero}
          <TrustSelftestPanel />
          {postureStrip}
          {digestSection}
          {residualSection}
          {registrySection}
          {sensitiveSection}
        </div>
      </div>
    </>
  );
}

// Page-local chrome only: layout + the instrument accents that aios.css scopes to
// other views. Every visual token comes from aios.css; nothing here asserts trust
// (no success/green fill) — the accent colour is driven by the honest integrity state.
const SEC_STYLE = `
.v-security .sec-nav-hint { color: var(--ink-muted); margin: -6px 0 var(--s5); }
.v-security .sec-sections { display: flex; flex-direction: column; gap: var(--s5); }

.v-security .sec-section { padding: var(--s5) var(--s6); }
.v-security .sec-section:focus { outline: none; }
.v-security .sec-section:focus-visible { outline: 2px solid var(--cyan); outline-offset: 3px; }
.v-security .sec-idx {
  font-family: var(--f-mono); font-size: 11px; font-weight: 700; color: var(--ink-muted);
  border: 1px solid rgb(var(--line-rgb)/.9); border-radius: var(--r-sm);
  min-width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center; padding: 0 5px;
}
.v-security .sec-hint { color: var(--ink-muted); margin: calc(var(--s4) * -1 + 2px) 0 var(--s4); }

/* ── 0 · THE MANIFEST instrument ─────────────────────────────────────────── */
.v-security .mani { --int: var(--warning); --int-rgb: var(--warning-rgb); }
.v-security .sec-int--checking { --int: var(--cyan); --int-rgb: var(--cyan-rgb); }
.v-security .sec-int--broken { --int: var(--danger); --int-rgb: var(--danger-rgb); }
.v-security .sec-int--blocked { --int: var(--warning); --int-rgb: var(--warning-rgb); }

.v-security .mani-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--s4); }
.v-security .mh-title { display: flex; flex-direction: column; gap: 5px; }
.v-security .mh-sub { color: var(--ink-muted); text-transform: none; letter-spacing: .02em; }

.v-security .mani-core {
  display: flex; align-items: center; gap: var(--s6); margin: var(--s5) 0 var(--s4); flex-wrap: wrap;
}
.v-security .mc-mark { position: relative; flex: none; width: 96px; height: 96px; display: grid; place-items: center; }
.v-security .mc-halo {
  position: absolute; inset: 8px; border-radius: 50%;
  border: 1.5px solid rgb(var(--int-rgb)/.5);
  box-shadow: 0 0 40px -6px rgb(var(--int-rgb)/.5), inset 0 0 22px -8px rgb(var(--int-rgb)/.6);
  animation: secHalo 2.6s ease-in-out infinite;
}
.v-security .sec-int--broken .mc-halo { animation-duration: 1.6s; }
@keyframes secHalo { 0%,100% { transform: scale(1); opacity: .85; } 50% { transform: scale(1.06); opacity: .45; } }
.v-security .mc-read { min-width: 0; flex: 1 1 300px; }
.v-security .mc-detail { color: var(--ink-muted); font-size: var(--t-small); margin: var(--s2) 0 0; max-width: 64ch; }
.v-security .mc-reason { color: var(--ink-muted); text-transform: none; letter-spacing: .01em; margin: 6px 0 0; }
.v-security .mani .chain { margin-top: var(--s3); }
.v-security .chain-note { color: var(--ink-muted); align-self: center; }

/* ── 1 · POSTURE STRIP ───────────────────────────────────────────────────── */
.v-security .astats { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--s4); }
.v-security .astat { display: grid; gap: 4px; position: relative; padding-left: 14px; }
.v-security .astat::before {
  content: ""; position: absolute; left: 0; top: 3px; bottom: 3px; width: 3px; border-radius: 3px;
  background: var(--ink-muted);
}
.v-security .astat.as-warn::before { background: var(--warning); box-shadow: 0 0 8px rgb(var(--warning-rgb)/.6); }
.v-security .astat.as-info::before { background: var(--cyan); box-shadow: 0 0 8px rgb(var(--cyan-rgb)/.6); }
.v-security .astat b { font-family: var(--f-mono); font-size: 30px; font-weight: 700; line-height: 1; letter-spacing: -.03em; }
.v-security .astat .micro { color: var(--ink-muted); }

/* ── shared re-dress: blocked note, digest, residuals, events ────────────── */
.v-security .sec-blocked {
  display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap;
  padding: var(--s3) var(--s4); border-radius: var(--r);
  background: rgb(var(--warning-rgb)/.07); border: 1px solid rgb(var(--warning-rgb)/.26);
}
.v-security .sec-blocked .note { font-size: var(--t-small); }
.v-security .sec-reason { margin: var(--s3) 0 0; }

.v-security .sec-digest-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: var(--s3); }
.v-security .sec-digest-val {
  font-size: 13px; color: var(--ink-muted);
  background: rgb(var(--surface-rgb)/.6); border: 1px solid rgb(var(--line-rgb)/.9);
  border-radius: var(--r-sm); padding: 6px 10px; overflow-x: auto;
}

.v-security .sec-residual-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.v-security .sec-residual-item {
  display: flex; align-items: center; justify-content: space-between; gap: var(--s3);
  padding: var(--s3) 0; border-bottom: 1px solid rgb(var(--line-rgb)/.6);
}
.v-security .sec-residual-item:last-child { border-bottom: none; }
.v-security .sec-residual-lead { display: inline-flex; align-items: center; gap: 10px; min-width: 0; }
.v-security .sec-residual-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.v-security .sec-events { display: flex; flex-direction: column; gap: var(--s2); }
.v-security .sec-event {
  display: flex; align-items: center; justify-content: space-between; gap: var(--s3);
  padding: var(--s3); border-radius: var(--r); border: 1px solid rgb(var(--line-rgb)/.6);
  background: rgb(var(--surface-rgb)/.4);
}
.v-security .se-lead { display: inline-flex; align-items: center; gap: var(--s2); min-width: 0; }
.v-security .se-lead .note { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.v-security .se-time { font-size: var(--t-small); color: var(--ink-muted); white-space: nowrap; }

@media (max-width: 640px) {
  .v-security .astats { grid-template-columns: 1fr 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .v-security .mc-halo { animation: none; }
}
`;
