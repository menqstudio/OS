import { useRef, type ReactNode, type KeyboardEvent, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { Skeleton, ErrorState, EmptyState } from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Mark } from '../components/Ambient';
import { TrustSelftestPanel } from '../components/TrustSelftest';
import { STR } from './Security.strings';

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
//
// # Motion (§D: "Motion: integrity pulse (`sigbreathe`)")
//
// The pulse is APPLIED, and it is BOUND to state. This box sat unticked on the roadmap
// as "deliberately not applied", on the reasoning that a breathing instrument would
// paint liveness onto a chain nothing has confirmed. That reasoning is right and the
// conclusion drawn from it was wrong twice over:
//
//   1. The page was ALREADY breathing. `.mc-halo` carried an unconditional
//      `secHalo 2.6s infinite`, so the instrument pulsed hardest in `blocked` — the
//      exact thing the comment two hundred lines above said it must not do. An honesty
//      argument written in a comment is not an honesty property of the page.
//   2. "Never animate" and "animate always" are not the only options. `checking` is a
//      chain read genuinely IN FLIGHT: motion there depicts something that is actually
//      happening. `broken` is an alert and §D asks for the faster danger cadence.
//      `blocked` is now, correctly, STILL.
//
// So the pulse says "this surface is reading the chain right now" — a fact the desktop
// can establish — and never "the chain is alive", which it cannot: `RECORDS_ARE_AUTHENTICATED`
// is permanently `false` (see `governance.rs`). A pulse gated on a CONFIRMED chain would
// have been a branch that can never run, which is the shape this repository deletes
// rather than ships.

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
 *  desktop has no live status feed for these, so each renders "unverified".
 *  Display names are trilingual and live in Security.strings.ts under
 *  `residual.<id>` — the id here doubles as the strings key. */
type ResidualId = 'O-1' | 'O-2' | 'O-3' | 'O-4' | 'O-5';

const RESIDUAL_IDS: ResidualId[] = ['O-1', 'O-2', 'O-3', 'O-4', 'O-5'];

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
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

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
  const blockedNote = (noteKey: keyof typeof STR) => (
    <div className="sec-blocked" role="note">
      <span className="pill warn">{L('blocked')}</span>
      <span className="note">{L(noteKey)}</span>
    </div>
  );

  // --- Honest posture labels (live region text) --------------------------------------
  const integrityLabel = integrity === 'checking'
    ? L('verifying')
    : integrity === 'broken'
      ? L('chainReadFailed')
      : L('integrityUnverified');
  const integrityDetail = integrity === 'checking'
    ? L('readingChain')
    : integrity === 'broken'
      ? L('integrityDetailBroken')
      : L('integrityDetailBlocked');

  // --- 0 · THE MANIFEST · chain-integrity instrument (REAL chain read, live region) --
  const integrityHero = (
    <section
      ref={(el) => { sectionRefs.current[0] = el; }}
      role="region"
      aria-labelledby="sec-integrity-h"
      tabIndex={0}
      className={`sec-section mani surface soft lg hud reveal sec-int--${integrity}${
        // §D's `sigbreathe` integrity pulse, BOUND to the one state that has liveness in
        // it. See the motion note in the module header. The class is in the DOM, not only
        // in the stylesheet, so a test can assert it per state and a mutation that applies
        // it unconditionally is caught.
        integrity === 'checking' ? ' sigbreathe' : ''
      }`}
      style={cv(1)}
    >
      <HudChrome />
      <div className="mani-head">
        <div className="mh-title">
          <h2 className="eyebrow" id="sec-integrity-h">
            {L('integrityHeading')}
          </h2>
          <span className="mh-sub micro">{L('adjudicatedByEngine')}</span>
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
            <p className="mc-reason micro">{L('engineReason')}{chainReason}</p>
          ) : null}
        </div>
      </div>

      {/* Non-live wire: the chain does not flow — nothing is confirmed. `.wire.live`
          exists in aios.css and is deliberately not used: a travelling dot would depict
          evidence moving, and no evidence has been authenticated here. Unlike the halo,
          this one was already honest. */}
      <div className="wire" />
      {/* Honest link chain: the three engine-truth surfaces, NONE confirmed
          (no `.done`/`.now`) — mirroring the blocked posture, not implying trust. */}
      <div className="chain" aria-label={L('engineSurfacesNoneConfirmed')}>
        <b>{L('digestChip')}</b>
        <b>{L('chainChip')}</b>
        <b>{L('leasesChip')}</b>
        <span className="micro chain-note">{L('unverifiedLower')}</span>
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
        {L('postureHint')}
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
    L('digestTitle'),
    L('digestHint'),
    <>
      <div className="sec-digest-row">
        <span className="micro">SHA-256</span>
        <code className="sec-digest-val mono">—</code>
      </div>
      {blockedNote('digestBlockedNote')}
      {chainReason ? (
        <p className="note sec-reason micro">{L('engineReason')}{chainReason}</p>
      ) : null}
    </>,
  );

  // --- 3 · Residual-item tracker O-1..O-5 (blocked: no live feed) ---------------------
  const residualSection = section(
    3,
    'sec-residual',
    L('residualTitle'),
    L('residualHint'),
    <ul className="sec-residual-list" role="list">
      {RESIDUAL_IDS.map((id) => (
        <li key={id} className="sec-residual-item" role="listitem">
          <span className="sec-residual-lead">
            <span className="tag">{id}</span>
            <span className="sec-residual-name">{L(`residual.${id}`)}</span>
          </span>
          <span className="pill warn">{L('unverified')}</span>
        </li>
      ))}
    </ul>,
  );

  // --- 4 · Key & lease registry (blocked by design: desktop caches nothing) ----------
  const registrySection = section(
    4,
    'sec-registry',
    L('registryTitle'),
    L('registryHint'),
    blockedNote('registryBlockedNote'),
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
            <span className="eyebrow">{L('eyebrowCore')}</span>
            <h1>{t('nav.security')}</h1>
            <p className="sub">{t('security.subtitle')}</p>
          </div>
          <div className="right">
            <Mark state={MARK_BY_INTEGRITY[integrity]} size={22} />
            <span className={`pill ${PILL_BY_INTEGRITY[integrity]}`}>{integrityLabel}</span>
          </div>
        </header>

        <p className="sec-nav-hint micro">
          {L('navHint')}
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
}
/* MOTION IS BOUND TO STATE. This halo used to animate unconditionally, which meant the
   instrument breathed hardest in "blocked" — the one state where nothing is established.
   The page argued in its own comments that a pulse would paint liveness onto an
   unconfirmed chain, and then painted it anyway, two hundred lines down in a stylesheet.
   "checking" is a read genuinely in flight; "broken" is an alert and takes the faster
   cadence §D asks for; "blocked" is still. */
.v-security .sec-int--checking .mc-halo { animation: secHalo 2.6s ease-in-out infinite; }
.v-security .sec-int--broken .mc-halo { animation: secHalo 1.6s ease-in-out infinite; }
@keyframes secHalo { 0%,100% { transform: scale(1); opacity: .85; } 50% { transform: scale(1.06); opacity: .45; } }
/* §D: "Motion: integrity pulse (sigbreathe)". The keyframe is the shared one from
   aios.css; --tone-rgb is what it reads, so the instrument hands it the cyan of the
   checking tone. It is applied by the sigbreathe class, which the component adds only
   in "checking" — the pulse means "this surface is reading the chain right now", which
   is a fact, and not "the chain is alive", which the desktop cannot establish. */
/* THE ENTRANCE ANIMATION MUST STAY IN THE LIST. This instrument carries the "reveal" class,
   which is "opacity:0; transform:translateY(14px); animation:reveal var(--enter) forwards"
   (aios.css) - the entrance animation is the ONLY thing that makes it visible. The first
   version of this rule used the animation SHORTHAND at higher specificity, which REPLACES the
   animation list, so reveal never ran and the instrument rendered at opacity:0, displaced 14px,
   for the whole of "checking". Measured in a real browser by the fifth independent audit
   (A-01); no test in this repository could see it, because vitest runs with css:false and
   Security.test.tsx asserts the class name, not the paint. tools/check_c1_tokens.py checks it
   statically now, and putting the shorthand back turns that gate RED.
   The delay is restated because the shorthand resets animation-delay too, and the reveal class
   sets it separately on the line below its own shorthand. */
.v-security .mani.sigbreathe {
  --tone-rgb: var(--cyan-rgb);
  animation: reveal var(--enter) forwards, sigbreathe 2.6s cubic-bezier(.4,0,.2,1) infinite;
  animation-delay: calc(var(--i, 0) * var(--stagger)), 0s;
}
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
  .v-security .sec-int--checking .mc-halo,
  .v-security .sec-int--broken .mc-halo,
  .v-security .mani.sigbreathe { animation: none; }
}
`;
