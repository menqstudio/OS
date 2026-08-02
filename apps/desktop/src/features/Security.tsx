import { useRef, type ReactNode, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Badge, Skeleton, ErrorState, EmptyState } from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Tone } from '../domain/enums';

// ⛨ Անվտանգություն — Evidence chain / posture (Phase-2 §D).
//
// Data honesty: the ONLY backing command that exists today is
// `get_security_summary` (posture counts + recent sensitive ActivityEvents),
// which drives the real "posture overview" and "sensitive events" sections.
// The four engine-truth components the spec names — chain-integrity view,
// protected control-plane digest, residual-item tracker (O-1..O-5) and the
// key/lease registry — read from the engine evidence chain, for which NO
// read-only IPC command is wired into the desktop yet. Rather than fabricate a
// "verified" chain or fake digests/leases, every one of those renders its
// honest `blocked` state: integrity is adjudicated by the engine's Ed25519
// system and the desktop caches no keys or leases by design.

/** Derived integrity of the evidence chain, from the real load state only.
 *  `verified` is intentionally NOT a value: the desktop has no chain-read
 *  command, so it never claims a good chain — steady state is `blocked`. */
type Integrity = 'checking' | 'broken' | 'blocked';

// Sections in tab order. Digit shortcuts (1..N) + `[` / `]` move focus between
// them, satisfying the spec's "sectioned tab order".
const SECTION_COUNT = 6;

const TONE_BY_INTEGRITY: Record<Integrity, Tone> = {
  checking: 'info',
  broken: 'danger',
  blocked: 'warning',
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

export function Security() {
  const { t, lang } = useApp();
  const s = useAsync(() => desktop.getSecuritySummary(), []);
  const tr = (en: string, hy: string) => (lang === 'hy' ? hy : en);

  const backend = hasBackend();
  // Honest derivation — never a fabricated "verified".
  const integrity: Integrity =
    s.loading && s.data === null ? 'checking'
      : s.error && backend ? 'broken'
        : 'blocked';

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

  // --- One section = a labelled, focusable landmark card ------------------------------
  const section = (index: number, id: string, title: string, hint: string | null, body: ReactNode) => (
    <section
      key={id}
      ref={(el) => { sectionRefs.current[index] = el; }}
      role="region"
      aria-labelledby={`${id}-h`}
      tabIndex={0}
      className="sec-section"
    >
      <div className="card">
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title" id={`${id}-h`}>{title}</div>
            <span className="sec-idx" aria-hidden="true">{index + 1}</span>
          </div>
          {hint && <div className="muted sec-hint">{hint}</div>}
          {body}
        </div>
      </div>
    </section>
  );

  // Honest "no read command wired" notice reused by every engine-truth section.
  const blockedNote = (extraEn: string, extraHy: string) => (
    <div className="sec-blocked" role="note">
      <Badge tone="warning">{tr('Blocked', 'Արգելափակված')}</Badge>
      <span className="muted">{tr(extraEn, extraHy)}</span>
    </div>
  );

  // --- 0 · Chain-integrity view (live region) ----------------------------------------
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

  const integritySection = section(
    0,
    'sec-integrity',
    tr('Evidence-chain integrity', 'Ապացույցների շղթայի ամբողջականություն'),
    null,
    <div className={`sec-integrity sec-integrity--${integrity}`}>
      <span className="sec-integrity-dot" aria-hidden="true" />
      <div
        className="sec-integrity-text"
        role="status"
        aria-live={integrity === 'broken' ? 'assertive' : 'polite'}
      >
        <Badge tone={TONE_BY_INTEGRITY[integrity]}>{integrityLabel}</Badge>
        <div className="muted" style={{ marginTop: 6, maxWidth: 620 }}>{integrityDetail}</div>
      </div>
    </div>,
  );

  // --- 1 · Posture overview (REAL data: get_security_summary) -------------------------
  const postureSection = section(
    1,
    'sec-posture',
    t('nav.security'),
    tr('Live posture counts from the engine audit summary.', 'Կենդանի ցուցանիշներ շարժիչի աուդիտի ամփոփումից։'),
    s.loading && s.data === null ? (
      <Skeleton rows={3} />
    ) : s.error ? (
      // ErrorState already renders the calm offline state when there is no backend.
      <ErrorState message={s.error} onRetry={s.reload} />
    ) : s.data ? (
      <div className="grid grid-3">
        <div className="sec-stat">
          <div className="sec-stat-num">{s.data.pendingApprovals}</div>
          <div className="muted">{t('security.pending')}</div>
        </div>
        <div className="sec-stat">
          <div className="sec-stat-num">{s.data.decidedApprovals}</div>
          <div className="muted">{t('security.decided')}</div>
        </div>
        <div className="sec-stat">
          <div className="sec-stat-num">{s.data.auditEvents}</div>
          <div className="muted">{t('security.audit')}</div>
        </div>
      </div>
    ) : null,
  );

  // --- 2 · Protected control-plane digest (blocked: no read command) -----------------
  const digestSection = section(
    2,
    'sec-digest',
    tr('Control-plane digest', 'Կառավարման հարթության ամփոփ (digest)'),
    tr('Read-only protected-control-plane digest.', 'Միայն-ընթերցման պաշտպանված կառավարման հարթության digest։'),
    <>
      <div className="sec-digest-row">
        <span className="field-label">SHA-256</span>
        <code className="sec-digest-val">—</code>
      </div>
      {blockedNote(
        'The protected control-plane digest is held by the engine; no read command is wired into the desktop yet.',
        'Պաշտպանված կառավարման հարթության digest-ը պահվում է շարժիչում. ընթերցման հրաման դեռ միացված չէ։',
      )}
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
          <span className="row" style={{ gap: 10, minWidth: 0 }}>
            <Badge tone="neutral">{r.id}</Badge>
            <span className="sec-residual-name">{tr(r.en, r.hy)}</span>
          </span>
          <Badge tone="warning">{tr('Unverified', 'Չհաստատված')}</Badge>
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
      <div className="stack">
        {s.data.sensitiveEvents.map((ev) => (
          <div key={ev.id} className="list-row">
            <span className="row" style={{ gap: 8 }}>
              <Badge tone="neutral">{ev.eventType}</Badge>
              <span className="muted">
                {ev.entityType ?? '—'}{ev.entityId ? ` · ${ev.entityId}` : ''}
              </span>
            </span>
            <span className="muted">{ev.createdAt}</span>
          </div>
        ))}
      </div>
    ),
  );

  return (
    <div className="sec-page" onKeyDown={onKeyDown}>
      <PageHeader title={t('nav.security')} subtitle={t('security.subtitle')} />

      <p className="sec-nav-hint muted">
        {tr('Press 1–6, or [ and ] to move between sections.', 'Սեղմեք 1–6, կամ [ և ] բաժինների միջև տեղափոխվելու համար։')}
      </p>

      <div className="sec-sections">
        {integritySection}
        {postureSection}
        {digestSection}
        {residualSection}
        {registrySection}
        {sensitiveSection}
      </div>

      <style>{`
        .sec-sections { display: flex; flex-direction: column; gap: var(--menq-space-4); }
        .sec-nav-hint { font-size: 12px; margin: -8px 0 var(--menq-space-4); }
        .sec-section { border-radius: var(--menq-radius-card); }
        .sec-section:focus { outline: none; }
        .sec-section:focus-visible { outline: 2px solid var(--brops-accent); outline-offset: 3px; }
        .sec-idx {
          font-size: 11px; font-weight: 700; color: var(--brops-muted);
          border: 1px solid var(--brops-border); border-radius: var(--menq-radius-sm);
          min-width: 18px; height: 18px; display: inline-flex; align-items: center;
          justify-content: center; padding: 0 4px;
        }
        .sec-hint { font-size: 12px; margin-top: -6px; }

        .sec-stat {
          background: var(--brops-bg); border: 1px solid var(--brops-border);
          border-radius: var(--menq-radius-md); padding: var(--menq-space-4);
        }
        .sec-stat-num { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; }

        /* integrity view + sigbreathe pulse */
        .sec-integrity { display: flex; align-items: flex-start; gap: var(--menq-space-4); }
        .sec-integrity-dot {
          flex: none; width: 14px; height: 14px; border-radius: 50%; margin-top: 4px;
          background: var(--menq-color-warning);
          box-shadow: 0 0 0 4px color-mix(in srgb, var(--menq-color-warning) 22%, transparent);
        }
        .sec-integrity--checking .sec-integrity-dot { background: var(--menq-color-info);
          box-shadow: 0 0 0 4px color-mix(in srgb, var(--menq-color-info) 22%, transparent); }
        .sec-integrity--broken .sec-integrity-dot { background: var(--menq-color-danger);
          box-shadow: 0 0 0 4px color-mix(in srgb, var(--menq-color-danger) 22%, transparent);
          animation: sigbreathe 1.8s ease-in-out infinite; }
        .sec-integrity--checking .sec-integrity-dot { animation: sigbreathe 2.4s ease-in-out infinite; }
        .sec-integrity-text { min-width: 0; }
        @keyframes sigbreathe {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.35); opacity: 0.55; }
        }
        @media (prefers-reduced-motion: reduce) {
          .sec-integrity-dot { animation: none !important; }
        }

        .sec-blocked {
          display: flex; align-items: center; gap: var(--menq-space-3); flex-wrap: wrap;
          padding: var(--menq-space-3) var(--menq-space-4);
          background: color-mix(in srgb, var(--menq-color-warning) 8%, transparent);
          border: 1px solid color-mix(in srgb, var(--menq-color-warning) 26%, transparent);
          border-radius: var(--menq-radius-md);
        }
        .sec-blocked .muted { font-size: 13px; }

        .sec-digest-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: var(--menq-space-3); }
        .sec-digest-val {
          font-family: var(--menq-font-mono); font-size: 13px; color: var(--brops-muted);
          background: var(--brops-bg); border: 1px solid var(--brops-border);
          border-radius: var(--menq-radius-sm); padding: 6px 10px; overflow-x: auto;
        }

        .sec-residual-list { list-style: none; margin: 0; padding: 0;
          display: flex; flex-direction: column; }
        .sec-residual-item {
          display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3);
          padding: var(--menq-space-3) 0; border-bottom: 1px solid var(--brops-border);
        }
        .sec-residual-item:last-child { border-bottom: none; }
        .sec-residual-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      `}</style>
    </div>
  );
}
