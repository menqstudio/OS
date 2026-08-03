import { useState } from 'react';
import { useApp } from '../app/store';
import { Skeleton, ErrorState, EmptyState } from '../components/ui';
import { Mark } from '../components/Ambient';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Lang, Theme } from '../domain/enums';
import { STR } from './Settings.strings';

// A read-only, accessible on/off indicator. Rendered as a disabled <button role="switch"> so the
// state is exposed non-visually through aria-checked (the governed provider is backend-owned and
// cannot be flipped from the desktop app — hence never operable, only reported).
function Switch(
  { checked, label, describedBy }:
  { checked: boolean; label: string; describedBy?: string },
) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      aria-disabled
      disabled
      className="set-sw"
    >
      <span className="set-sw-knob" aria-hidden="true" />
    </button>
  );
}

export function Settings() {
  const { t, theme, toggleTheme, lang, setLang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

  // Polite, screen-reader-only announcement of a just-applied preference change.
  const [announce, setAnnounce] = useState('');

  const selectTheme = (value: Theme) => {
    if (value !== theme) toggleTheme();
    setAnnounce(`${L('themeChanged')} ${value === 'dark' ? t('settings.theme.dark') : t('settings.theme.light')}`);
  };

  const selectLang = (value: Lang) => {
    setLang(value);
    setAnnounce(`${L('languageChanged')} ${languageNames[value]}`);
  };

  // Read-only, HONEST view of the runtime the backend actually resolved. The provider/model/governed
  // state is chosen by the backend environment (fail-closed policy in ai.rs) — there is no client-side
  // toggle that could re-seat the engine or route turns through the wall. Theme/language are the only
  // writable settings (localStorage-backed store owned by app/store.tsx via useApp).
  const ai = useAsync(() => desktop.aiStatus(), []);

  const data = ai.data;
  const isNone = data?.provider === 'none';
  const isGoverned = !!data?.governed;
  const ready = !!data?.ready;
  // governed provider enabled but the sidecar never became ready → fail-closed guidance, no result.
  const sidecarBlocked = !!data && isGoverned && !ready;
  // engine-down dims the model dock + runtime name exactly like the mockup's offline state.
  const engineDown = !!data && !isNone && !ready;

  // Runtime power mark, mapped from REAL aiStatus — live only when the backend reports ready,
  // otherwise idle. Never forced to a green/live state.
  const markState = ready ? 'live' : 'idle';
  // Provider socket state class (honest): live when ready, locked when governed-but-not-ready
  // (fail-closed), idle otherwise.
  const provSt = ready ? 'live' : isGoverned ? 'locked' : 'idle';

  // Honest bay-state pill computed from the real request lifecycle + status.
  const bayPill: { tone: string; label: string } = !hasBackend()
    ? { tone: 'off', label: L('bayUnavailable') }
    : ai.loading && data === null
      ? { tone: 'info', label: L('bayChecking') }
      : ai.error
        ? { tone: 'warn', label: L('bayError') }
        : isNone
          ? { tone: 'warn', label: L('bayUnset') }
          : ready
            ? { tone: 'info', label: L('bayRunning') }
            : { tone: 'warn', label: L('bayOffline') };

  return (
    <div className={`v-settings${engineDown ? ' engine-down' : ''}`}>
      <style>{`
        .v-settings .set-sr-only {
          position:absolute; width:1px; height:1px; padding:0; margin:-1px;
          overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; border:0;
        }
        .v-settings .set-toggle { display:flex; align-items:center; justify-content:space-between; gap:var(--s4); margin-top:var(--s4); }
        .v-settings .set-toggle > span:first-child { font-size:13px; color:var(--ink); }
        .v-settings .set-note { color:var(--ink-muted); font-size:12px; line-height:1.55; max-width:64ch; }
        .v-settings .set-sw {
          position:relative; width:42px; height:24px; flex:0 0 auto; padding:0; cursor:not-allowed;
          border-radius:var(--r-pill); border:1px solid rgb(var(--cyan-rgb)/.25); background:rgb(var(--raised-rgb)/.6);
          transition:background .18s, border-color .18s; opacity:.85;
        }
        .v-settings .set-sw[aria-checked="true"] { background:rgb(var(--success-rgb)/.5); border-color:rgb(var(--success-rgb)/.5); }
        .v-settings .set-sw-knob {
          position:absolute; top:2px; left:2px; width:18px; height:18px; border-radius:50%;
          background:var(--ink); box-shadow:0 1px 3px rgb(0 0 0/.45); transition:transform .18s;
        }
        .v-settings .set-sw[aria-checked="true"] .set-sw-knob { transform:translateX(18px); }
        .v-settings .set-sw:focus-visible { outline:2px solid var(--cyan); outline-offset:2px; }
        .v-settings .set-lang { display:flex; align-items:center; justify-content:space-between; gap:var(--s4); }
        .v-settings .set-lang select {
          height:32px; padding:0 10px; border-radius:var(--r-sm); color:var(--ink);
          background:rgb(var(--raised-rgb)/.6); border:1px solid rgb(var(--cyan-rgb)/.25); font-size:13px;
        }
        .v-settings .set-lang select:focus-visible { outline:none; border-color:rgb(var(--cyan-rgb)/.5); box-shadow:0 0 0 3px rgb(var(--cyan-rgb)/.15); }
        .v-settings .set-blocked {
          margin-top:var(--s4); padding:var(--s4); border-radius:var(--r);
          border:1px solid rgb(var(--danger-rgb)/.45); background:rgb(var(--danger-rgb)/.10);
        }
        .v-settings .set-blocked-title { display:flex; gap:8px; align-items:center; font-weight:700; color:var(--danger); }
        .v-settings .set-blocked ol { margin:10px 0 0; padding-left:20px; color:var(--ink); font-size:13px; }
        .v-settings .set-blocked li { margin:4px 0; }
        .v-settings .rt-state-row { display:flex; align-items:center; gap:8px; margin-top:var(--s3); }
        @media (prefers-reduced-motion: reduce) { .v-settings .set-sw, .v-settings .set-sw-knob { transition:none; } }
      `}</style>

      <header className="pageHead">
        <div>
          <span className="eyebrow">{L('eyebrowControlRoom')}</span>
          <h1>{t('nav.settings')}</h1>
          <p className="sub">{t('settings.subtitle')}</p>
        </div>
        <div className="right">
          {data && !isNone && (
            <span className={`pill ${isGoverned && ready ? 'live' : 'warn'}`}>
              {isGoverned ? t('settings.governed') : t('settings.ungoverned')}
            </span>
          )}
        </div>
      </header>

      {/* Polite live region: announces an applied preference change without stealing focus. */}
      <div className="set-sr-only" role="status" aria-live="polite">{announce}</div>

      {/* ═══ HERO · ENGINE BAY — the real AI runtime the backend resolved (read-only) ═══ */}
      <section className="set-bay surface soft lg hud reveal" aria-label={t('settings.aiProvider')}>
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />

        <div className="bay-top">
          <span className="eyebrow">{L('eyebrowRuntimeConsole')}</span>
          <span className={`pill ${bayPill.tone}`}>{bayPill.label}</span>
        </div>

        <p className="set-note" style={{ marginBottom: 'var(--s5)' }}>{t('settings.aiProviderHint')}</p>

        {!hasBackend() && <span className="set-note">{t('settings.aiProviderUnavailable')}</span>}

        {hasBackend() && (
          <>
            {ai.loading && data === null && <Skeleton rows={2} />}
            {ai.error && <ErrorState message={ai.error} onRetry={ai.reload} />}
            {data && isNone && (
              <EmptyState
                glyph="◍"
                title={t('settings.aiProviderNotConfigured')}
                hint={L('providerNotConfiguredHint')}
              />
            )}

            {data && !isNone && (
              <div className="bay-rig">
                {/* — dock 1 · PROVIDER (the resolved provider, read-only) — */}
                <div className="dock-bay db-prov">
                  <span className="db-cap"><i className="db-i">01</i>{L('capProvider')}</span>
                  <div className="psock-list">
                    <div
                      className={`psock seated pst-${provSt}`}
                      role="group"
                      aria-label={`${data.provider} — ${ready ? t('settings.aiProviderReady') : t('settings.aiProviderNotReady')}`}
                    >
                      <span className="ps-jack" aria-hidden="true"><i /></span>
                      <span className="ps-body">
                        <span className="ps-top">
                          <b>{data.provider}</b>
                          <span className="tag">{isGoverned ? t('settings.governed') : t('settings.ungoverned')}</span>
                        </span>
                      </span>
                      <span className="ps-st micro">
                        {ready ? t('settings.aiProviderReady') : t('settings.aiProviderNotReady')}
                      </span>
                    </div>
                  </div>

                  {/* Governed-provider toggle — honestly read-only (backend-owned, fail-closed). */}
                  <div className="set-toggle">
                    <span id="settings-governed-label">{L('governedToggleLabel')}</span>
                    <Switch
                      checked={isGoverned}
                      label={L('governedToggleLabel')}
                      describedBy="settings-governed-desc"
                    />
                  </div>
                  <p id="settings-governed-desc" className="set-note db-hint">{L('governedToggleDesc')}</p>
                </div>

                {/* bus link prov → model (flows only when the engine is live) */}
                <span className={`bay-link${ready ? ' flowing' : ''}`} data-seg="1" aria-hidden="true"><i className="bl-dot" /></span>

                {/* — dock 2 · MODEL (real resolved model, or honest empty) — */}
                <div className="dock-bay db-model">
                  <span className="db-cap"><i className="db-i">02</i>{L('capModel')}</span>
                  <div className="mchip">
                    {data.model ? (
                      <>
                        <div className="mc-top">
                          <span className="mc-name mono">{data.model}</span>
                        </div>
                        {data.detail && <p className="mc-note micro">{data.detail}</p>}
                      </>
                    ) : (
                      <p className="mc-note micro">{L('noModel')}</p>
                    )}
                  </div>
                </div>

                {/* bus link model → runtime */}
                <span className={`bay-link${ready ? ' flowing' : ''}`} data-seg="2" aria-hidden="true"><i className="bl-dot" /></span>

                {/* — dock 3 · RUNTIME (Bro) — power mark mapped from REAL aiStatus — */}
                <div className="dock-bay db-run">
                  <span className="db-cap"><i className="db-i">03</i>{L('capRuntime')}</span>
                  <div className="rt-core">
                    <span className="rt-halo" aria-hidden="true" />
                    <span className="rt-mark"><Mark state={markState} size={30} /></span>
                    <span className="rt-name micro">
                      {ready ? data.model || data.provider : L('noModel')}
                    </span>
                  </div>

                  {/* Governance readout derived from the real ai_status (honest, badge-free reasons). */}
                  {sidecarBlocked ? (
                    <div className="set-blocked" role="group" aria-label={L('blockedTitle')}>
                      <div className="set-blocked-title"><span aria-hidden="true">⛔</span> {L('blockedTitle')}</div>
                      {data.detail && <p className="set-note" style={{ marginTop: 6 }}>{data.detail}</p>}
                      <p className="set-note" style={{ marginTop: 6 }}>{L('blockedGuideIntro')}</p>
                      <ol>
                        <li>{L('blockedStep1')}</li>
                        <li>{L('blockedStep2')}</li>
                        <li>{L('blockedStep3')}</li>
                      </ol>
                      <div style={{ marginTop: 12 }}>
                        <button type="button" className="chip" onClick={ai.reload}>{L('recheck')}</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="rt-state-row">
                        <span className={`pill ${isGoverned && ready ? 'live' : 'warn'}`}>
                          {isGoverned ? t('settings.governed') : t('settings.ungoverned')}
                        </span>
                      </div>
                      <p className="set-note" style={{ marginTop: 8 }}>
                        {isGoverned && ready ? L('sidecarHealthyDesc') : L('sidecarInactiveDesc')}
                      </p>
                    </>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        <div className="bay-foot">
          <span className="micro bay-note">{L('runtimeDesc')}</span>
        </div>
      </section>

      {/* ═══ QUIET TIER · control panels ═══ */}
      <div className="set-grid">

        {/* — APPEARANCE · theme (real toggle) + language (real setLang) — */}
        <section className="surface soft set-panel set-theme reveal" aria-label={t('settings.appearance')}>
          <div className="sec-head">
            <h2>{t('settings.appearance')}</h2>
            <span className="note">{L('appearanceDesc')}</span>
          </div>

          <div
            className="theme-tiles"
            role="group"
            aria-labelledby="settings-theme-label"
            aria-describedby="settings-theme-desc"
          >
            <span id="settings-theme-label" className="set-sr-only">{t('settings.theme')}</span>
            <button
              type="button"
              className={`ttile tt-dark${theme === 'dark' ? ' on' : ''}`}
              aria-pressed={theme === 'dark'}
              aria-label={t('settings.theme.dark')}
              onClick={() => selectTheme('dark')}
            >
              <span className="tt-prev" aria-hidden="true">
                <span className="tt-bar" /><span className="tt-line" /><span className="tt-line s" /><span className="tt-glow" />
              </span>
              <span className="tt-meta"><b>{t('settings.theme.dark')}</b><i className="micro">DARK</i></span>
              <span className="tt-check" aria-hidden="true">✓</span>
            </button>
            <button
              type="button"
              className={`ttile tt-light${theme === 'light' ? ' on' : ''}`}
              aria-pressed={theme === 'light'}
              aria-label={t('settings.theme.light')}
              onClick={() => selectTheme('light')}
            >
              <span className="tt-prev" aria-hidden="true">
                <span className="tt-bar" /><span className="tt-line" /><span className="tt-line s" /><span className="tt-glow" />
              </span>
              <span className="tt-meta"><b>{t('settings.theme.light')}</b><i className="micro">LIGHT</i></span>
              <span className="tt-check" aria-hidden="true">✓</span>
            </button>
          </div>
          <span id="settings-theme-desc" className="set-note">{L('themeDesc')}</span>

          <div className="set-lang">
            <label htmlFor="settings-language">{t('settings.language')}</label>
            <select
              id="settings-language"
              value={lang}
              aria-describedby="settings-language-desc"
              onChange={(e) => selectLang(e.target.value as Lang)}
            >
              {(Object.keys(languageNames) as Lang[]).map((code) => (
                <option key={code} value={code}>{languageNames[code]}</option>
              ))}
            </select>
          </div>
          <span id="settings-language-desc" className="set-note">{L('languageDesc')}</span>

          {/* Fixed brand accent — decorative, not a user control. */}
          <div className="accent-rail" aria-hidden="true">
            <span className="micro">{L('accentLabel')}</span>
            <span className="acc-dot ad-cyan" /><span className="acc-dot ad-azure" /><span className="acc-dot ad-mint" />
            <span className="micro acc-note">{L('accentNote')}</span>
          </div>
        </section>

        {/* — SYSTEM IDENTITY · real About values only — */}
        <section className="surface soft set-panel set-sys reveal" aria-label={t('nav.settings')}>
          <div className="sec-head">
            <h2>{L('systemHeading')}</h2>
            <span className={`pill ${data?.ready ? 'live' : 'off'}`}>
              {data?.ready ? t('settings.aiProviderReady') : t('settings.aiProviderNotReady')}
            </span>
          </div>
          <div className="sys-id">
            <span className="seal" aria-hidden="true">◈</span>
            <div className="sys-idt"><b>MENQ OS</b><span className="micro mono">v0.9 · MenQ Studio</span></div>
          </div>
          <div className="sys-rows">
            <div className="sys-row"><span className="sys-k">{L('aboutProductLabel')}</span><b>MENQ OS</b></div>
            <div className="sys-row"><span className="sys-k">{L('aboutVersionLabel')}</span><b className="mono">v0.9</b></div>
            <div className="sys-row"><span className="sys-k">{L('aboutGovernanceLabel')}</span><b>{L('aboutGovernanceValue')}</b></div>
          </div>
        </section>

      </div>
    </div>
  );
}
