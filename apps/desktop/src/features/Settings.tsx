import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState } from '../components/ui';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Lang, Theme } from '../domain/enums';

// -------------------------------------------------------------------------------------------------
// Local, page-scoped bilingual copy (EN + HY). Per the thin-page convention this page inlines its
// own strings for the §D surfaces that are not yet in the shared i18n dictionaries — it never edits
// the shared i18n files. Keys already present in i18n/en.ts + hy.ts are used through `t()`.
// -------------------------------------------------------------------------------------------------
interface Str { en: string; hy: string }
const copy = {
  appearanceDesc: {
    en: 'Visual theme and interface language. Preferences are saved to this device.',
    hy: 'Տեսքի ոճ և ինտերֆեյսի լեզու։ Նախապատվությունները պահվում են այս սարքում։',
  },
  themeDesc: {
    en: 'Choose a light or dark interface. Motion is reduced automatically when your system asks for it.',
    hy: 'Ընտրեք բաց կամ մուգ ինտերֆեյս։ Շարժումը նվազում է ինքնաշխատ, երբ համակարգը դա պահանջում է։',
  },
  languageDesc: {
    en: 'Interface language for BroPS.',
    hy: 'BroPS-ի ինտերֆեյսի լեզուն։',
  },
  governedToggleLabel: { en: 'Governed provider', hy: 'Կառավարվող մատակարար' },
  governedToggleDesc: {
    en: 'Set by the backend environment under the fail-closed policy. This control is read-only — the desktop app never holds keys or leases and cannot route turns through the wall from here.',
    hy: 'Սահմանվում է backend-ի միջավայրի կողմից՝ fail-closed քաղաքականությամբ։ Այս կարգավորումը միայն կարդալու համար է. desktop ծրագիրը երբեք չի պահում բանալիներ կամ վարձակալություններ և չի կարող այստեղից ուղղորդել շրջադարձերը պատի միջով։',
  },
  sidecar: { en: 'Governance sidecar', hy: 'Կառավարման կողմնակի ծառայություն' },
  sidecarDesc: {
    en: 'The trusted engine that verifies governed turns and issues signed receipts.',
    hy: 'Վստահված շարժիչը, որը ստուգում է կառավարվող շրջադարձերը և թողարկում ստորագրված անդորրագրեր։',
  },
  sidecarHealthy: { en: 'Sidecar reachable', hy: 'Կողմնակի ծառայությունը հասանելի է' },
  sidecarHealthyDesc: {
    en: 'The governance engine responded and the governed path is available.',
    hy: 'Կառավարման շարժիչը պատասխանեց, և կառավարվող ուղին հասանելի է։',
  },
  sidecarInactive: { en: 'Sidecar inactive', hy: 'Կողմնակի ծառայությունն անգործուն է' },
  sidecarInactiveDesc: {
    en: 'The resolved provider is ungoverned, so no governance sidecar is engaged. Turns are not verified.',
    hy: 'Ընտրված մատակարարը չկառավարվող է, ուստի կառավարման կողմնակի ծառայությունը ներգրավված չէ։ Շրջադարձերը չեն ստուգվում։',
  },
  blockedTitle: { en: 'Sidecar misconfigured — governed path is fail-closed', hy: 'Կողմնակի ծառայությունը սխալ է կարգավորված — կառավարվող ուղին fail-closed է' },
  blockedGuideIntro: {
    en: 'The governed provider is enabled but the sidecar did not become ready, so every governed turn is blocked (no result is produced). To restore the governed path:',
    hy: 'Կառավարվող մատակարարը միացված է, բայց կողմնակի ծառայությունը պատրաստ չդարձավ, ուստի յուրաքանչյուր կառավարվող շրջադարձ արգելափակված է (արդյունք չի ստեղծվում)։ Կառավարվող ուղին վերականգնելու համար՝',
  },
  blockedStep1: {
    en: 'Confirm the governance engine / broker service is running in the backend environment.',
    hy: 'Հաստատեք, որ կառավարման շարժիչը / broker ծառայությունը աշխատում է backend միջավայրում։',
  },
  blockedStep2: {
    en: 'Provision the trust root so signed receipts can be verified (do not fall back to ungoverned).',
    hy: 'Ապահովեք վստահության արմատը, որպեսզի ստորագրված անդորրագրերը ստուգվեն (մի անցեք չկառավարվողի)։',
  },
  blockedStep3: {
    en: 'Re-check status once the sidecar is configured.',
    hy: 'Կրկին ստուգեք վիճակը, երբ կողմնակի ծառայությունը կարգավորված է։',
  },
  recheck: { en: 'Re-check', hy: 'Կրկին ստուգել' },
  about: { en: 'About', hy: 'Ծրագրի մասին' },
  aboutProductLabel: { en: 'Product', hy: 'Արտադրանք' },
  aboutVersionLabel: { en: 'Version', hy: 'Տարբերակ' },
  aboutGovernanceLabel: { en: 'Governance', hy: 'Կառավարում' },
  aboutGovernanceValue: {
    en: 'Fail-closed, verified-receipt-mandatory',
    hy: 'Fail-closed, պարտադիր ստուգված անդորրագրով',
  },
  providerNotConfiguredHint: {
    en: 'No AI provider is resolved by the backend environment. Configure one to enable turns.',
    hy: 'Backend միջավայրը AI մատակարար չի ընտրել։ Կարգավորեք մեկը՝ շրջադարձերը միացնելու համար։',
  },
  themeChanged: { en: 'Theme set to', hy: 'Տեսքի ոճը սահմանված է՝' },
  languageChanged: { en: 'Language set to', hy: 'Լեզուն սահմանված է՝' },
} satisfies Record<string, Str>;

// Local switch — an accessible on/off control. A native <button role="switch"> responds to both
// Space and Enter (satisfying the §D "toggles Space" requirement) and exposes aria-checked.
function Switch(
  { checked, disabled, label, describedBy, onChange }:
  { checked: boolean; disabled?: boolean; label: string; describedBy?: string; onChange?: (v: boolean) => void },
) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      className={`settings-switch${checked ? ' settings-switch--on' : ''}`}
      onClick={() => { if (!disabled && onChange) onChange(!checked); }}
    >
      <span className="settings-switch-knob" />
    </button>
  );
}

export function Settings() {
  const { t, theme, toggleTheme, lang, setLang } = useApp();
  const pick = (m: Str) => (lang === 'hy' ? m.hy : m.en);

  // Polite, screen-reader-only announcement of a just-applied preference change.
  const [announce, setAnnounce] = useState('');

  const selectTheme = (value: Theme) => {
    if (value !== theme) toggleTheme();
    setAnnounce(`${pick(copy.themeChanged)} ${value === 'dark' ? t('settings.theme.dark') : t('settings.theme.light')}`);
  };

  const selectLang = (value: Lang) => {
    setLang(value);
    setAnnounce(`${pick(copy.languageChanged)} ${languageNames[value]}`);
  };

  // Read-only, HONEST view of the provider the backend actually resolved. The provider is chosen by
  // the backend environment (fail-closed policy in ai.rs) — there is no client-side toggle that could
  // route turns through the wall. `desktop.settings store` for user prefs (theme/language) is the
  // localStorage-backed store owned by app/store.tsx; there is no `set_setting` command for the
  // provider, so the governed toggle below is rendered read-only rather than fabricated as writable.
  const ai = useAsync(() => desktop.aiStatus(), []);

  const data = ai.data;
  const isNone = data?.provider === 'none';
  const isGoverned = !!data?.governed;
  // §D `blocked`: governed provider enabled but the sidecar never became ready → fail-closed guidance.
  const sidecarBlocked = !!data && isGoverned && !data.ready;

  return (
    <>
      <style>{`
        .settings-section { animation: settings-reveal var(--menq-motion-med) ease-out both; }
        @keyframes settings-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        .settings-desc { color: var(--brops-muted); font-size: 12px; max-width: 560px; }
        .settings-seg { display: inline-flex; gap: var(--menq-space-2); }
        .settings-switch {
          position: relative; width: 42px; height: 24px; flex: none; padding: 0; cursor: pointer;
          border-radius: var(--menq-radius-pill); border: 1px solid var(--brops-border);
          background: var(--menq-color-hover);
          transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast);
        }
        .settings-switch--on { background: var(--brops-accent); border-color: transparent; }
        .settings-switch:disabled { cursor: not-allowed; opacity: 0.7; }
        .settings-switch-knob {
          position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%;
          background: var(--brops-surface); box-shadow: var(--menq-shadow-1);
          transition: transform var(--menq-motion-fast);
        }
        .settings-switch--on .settings-switch-knob { transform: translateX(18px); }
        .settings-switch:focus-visible { outline: 2px solid var(--menq-color-focus); outline-offset: 2px; }
        .settings-blocked {
          border: 1px solid color-mix(in srgb, var(--menq-color-danger) 45%, transparent);
          background: color-mix(in srgb, var(--menq-color-danger) 10%, transparent);
          border-radius: var(--menq-radius-md); padding: var(--menq-space-4);
        }
        .settings-blocked-title { font-weight: 700; color: var(--menq-color-danger); display: flex; gap: 8px; align-items: center; }
        .settings-blocked ol { margin: 10px 0 0; padding-left: 20px; color: var(--brops-text); font-size: 13px; }
        .settings-blocked li { margin: 4px 0; }
        .settings-sr-only {
          position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
          overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
        }
        .settings-about-key { color: var(--brops-muted); }
        @media (prefers-reduced-motion: reduce) {
          .settings-section { animation: none; }
          .settings-switch, .settings-switch-knob { transition: none; }
        }
      `}</style>

      <PageHeader title={t('nav.settings')} subtitle={t('settings.subtitle')} />

      {/* Polite live region: announces an applied preference change without stealing focus. */}
      <div className="settings-sr-only" role="status" aria-live="polite">{announce}</div>

      {/* -- Appearance / theme + language (real desktop settings store: localStorage via app store) -- */}
      <section className="settings-section" aria-label={t('settings.appearance')} style={{ animationDelay: '0ms' }}>
        <Panel title={t('settings.appearance')}>
          <div className="stack">
            <span className="settings-desc">{pick(copy.appearanceDesc)}</span>

            <div className="list-row">
              <span id="settings-theme-label">{t('settings.theme')}</span>
              <div
                className="settings-seg"
                id="settings-theme"
                role="group"
                aria-labelledby="settings-theme-label"
                aria-describedby="settings-theme-desc"
              >
                <Button variant={theme === 'dark' ? 'primary' : 'default'} onClick={() => selectTheme('dark')}>
                  {t('settings.theme.dark')}
                </Button>
                <Button variant={theme === 'light' ? 'primary' : 'default'} onClick={() => selectTheme('light')}>
                  {t('settings.theme.light')}
                </Button>
              </div>
            </div>
            <span id="settings-theme-desc" className="settings-desc">{pick(copy.themeDesc)}</span>

            <div className="list-row">
              <label htmlFor="settings-language">{t('settings.language')}</label>
              <select
                id="settings-language"
                className="select"
                style={{ width: 'auto' }}
                value={lang}
                aria-describedby="settings-language-desc"
                onChange={(e) => selectLang(e.target.value as Lang)}
              >
                {(Object.keys(languageNames) as Lang[]).map((code) => (
                  <option key={code} value={code}>
                    {languageNames[code]}
                  </option>
                ))}
              </select>
            </div>
            <span id="settings-language-desc" className="settings-desc">{pick(copy.languageDesc)}</span>
          </div>
        </Panel>
      </section>

      {/* -- AI provider (read-only, resolved by backend env) incl. the Phase-1 governed toggle -- */}
      <section className="settings-section" aria-label={t('settings.aiProvider')} style={{ animationDelay: '60ms' }}>
        <Panel title={t('settings.aiProvider')}>
          <div className="stack">
            <span id="settings-provider-desc" className="settings-desc">{t('settings.aiProviderHint')}</span>

            {/* Phase-1 governed-provider toggle — honestly read-only (backend-owned, fail-closed). */}
            <div className="list-row">
              <label id="settings-governed-label">{pick(copy.governedToggleLabel)}</label>
              <Switch
                checked={isGoverned}
                disabled
                label={pick(copy.governedToggleLabel)}
                describedBy="settings-governed-desc"
              />
            </div>
            <span id="settings-governed-desc" className="settings-desc">{pick(copy.governedToggleDesc)}</span>

            {!hasBackend() && <span className="muted">{t('settings.aiProviderUnavailable')}</span>}
            {hasBackend() && (
              <>
                {ai.loading && data === null && <Skeleton rows={2} />}
                {ai.error && <ErrorState message={ai.error} onRetry={ai.reload} />}
                {data && isNone && (
                  <EmptyState
                    glyph="◍"
                    title={t('settings.aiProviderNotConfigured')}
                    hint={pick(copy.providerNotConfiguredHint)}
                  />
                )}
                {data && !isNone && (
                  <>
                    <div className="list-row">
                      <span>
                        {data.provider}
                        {data.model && (
                          <span className="muted" style={{ display: 'block', fontSize: 12, marginTop: 2 }}>
                            {data.model}
                          </span>
                        )}
                      </span>
                      <span className="row">
                        <Badge tone={isGoverned ? 'success' : 'danger'}>
                          {isGoverned ? t('settings.governed') : t('settings.ungoverned')}
                        </Badge>
                        <Badge tone={data.ready ? 'success' : 'warning'}>
                          {data.ready ? t('settings.aiProviderReady') : t('settings.aiProviderNotReady')}
                        </Badge>
                      </span>
                    </div>
                    {data.detail && (
                      <span className="settings-desc">{data.detail}</span>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </Panel>
      </section>

      {/* -- Governance sidecar config — derives its state from the real ai_status; renders §D blocked -- */}
      <section className="settings-section" aria-label={pick(copy.sidecar)} style={{ animationDelay: '120ms' }}>
        <Panel title={pick(copy.sidecar)}>
          <div className="stack">
            <span className="settings-desc">{pick(copy.sidecarDesc)}</span>

            {!hasBackend() && <span className="muted">{t('settings.aiProviderUnavailable')}</span>}
            {hasBackend() && (
              <>
                {ai.loading && data === null && <Skeleton rows={2} />}
                {ai.error && <ErrorState message={ai.error} onRetry={ai.reload} />}

                {data && isNone && (
                  <EmptyState
                    glyph="◍"
                    title={t('settings.aiProviderNotConfigured')}
                    hint={pick(copy.providerNotConfiguredHint)}
                  />
                )}

                {/* blocked: governed but sidecar not ready → fail-closed guidance, no result. */}
                {sidecarBlocked && (
                  <div className="settings-blocked" role="group" aria-label={pick(copy.blockedTitle)}>
                    <div className="settings-blocked-title">⛔ {pick(copy.blockedTitle)}</div>
                    {data?.detail && (
                      <div className="settings-desc" style={{ marginTop: 6 }}>{data.detail}</div>
                    )}
                    <div className="settings-desc" style={{ marginTop: 6 }}>{pick(copy.blockedGuideIntro)}</div>
                    <ol>
                      <li>{pick(copy.blockedStep1)}</li>
                      <li>{pick(copy.blockedStep2)}</li>
                      <li>{pick(copy.blockedStep3)}</li>
                    </ol>
                    <div style={{ marginTop: 12 }}>
                      <Button small onClick={ai.reload}>{pick(copy.recheck)}</Button>
                    </div>
                  </div>
                )}

                {/* governed + ready → sidecar reachable */}
                {data && isGoverned && data.ready && (
                  <div className="list-row">
                    <span>{pick(copy.sidecarHealthy)}</span>
                    <Badge tone="success">{t('settings.aiProviderReady')}</Badge>
                  </div>
                )}
                {data && isGoverned && data.ready && (
                  <span className="settings-desc">{pick(copy.sidecarHealthyDesc)}</span>
                )}

                {/* ungoverned provider → no sidecar engaged (honest, not an error) */}
                {data && !isNone && !isGoverned && (
                  <>
                    <div className="list-row">
                      <span>{pick(copy.sidecarInactive)}</span>
                      <Badge tone="warning">{t('settings.ungoverned')}</Badge>
                    </div>
                    <span className="settings-desc">{pick(copy.sidecarInactiveDesc)}</span>
                  </>
                )}
              </>
            )}
          </div>
        </Panel>
      </section>

      {/* -- About -- */}
      <section className="settings-section" aria-label={pick(copy.about)} style={{ animationDelay: '180ms' }}>
        <Panel title={pick(copy.about)}>
          <div className="stack">
            <div className="list-row">
              <span className="settings-about-key">{pick(copy.aboutProductLabel)}</span>
              <span>MENQ OS</span>
            </div>
            <div className="list-row">
              <span className="settings-about-key">{pick(copy.aboutVersionLabel)}</span>
              <span>v0.9</span>
            </div>
            <div className="list-row">
              <span className="settings-about-key">{pick(copy.aboutGovernanceLabel)}</span>
              <span>{pick(copy.aboutGovernanceValue)}</span>
            </div>
          </div>
        </Panel>
      </section>
    </>
  );
}
