import { useApp } from '../app/store';
import { PageHeader, Panel, Button } from '../components/ui';
import { languageNames } from '../i18n';
import type { Lang, Theme } from '../domain/enums';

export function Settings() {
  const { t, theme, toggleTheme, lang, setLang, governedEngine, setGovernedEngine } = useApp();

  const selectTheme = (value: Theme) => {
    if (value !== theme) toggleTheme();
  };

  return (
    <>
      <PageHeader title={t('nav.settings')} subtitle={t('settings.subtitle')} />

      <Panel title={t('settings.appearance')}>
        <div className="stack">
          <div className="list-row">
            <span>{t('settings.theme')}</span>
            <span className="row">
              <Button variant={theme === 'dark' ? 'primary' : 'default'} onClick={() => selectTheme('dark')}>
                {t('settings.theme.dark')}
              </Button>
              <Button variant={theme === 'light' ? 'primary' : 'default'} onClick={() => selectTheme('light')}>
                {t('settings.theme.light')}
              </Button>
            </span>
          </div>

          <div className="list-row">
            <span>{t('settings.language')}</span>
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
              {(Object.keys(languageNames) as Lang[]).map((code) => (
                <option key={code} value={code}>
                  {languageNames[code]}
                </option>
              ))}
            </select>
          </div>

          <div className="list-row">
            <span>
              {t('settings.governedEngine')}
              <span className="muted" style={{ display: 'block', fontSize: 12, marginTop: 2, maxWidth: 420 }}>
                {t('settings.governedEngineHint')}
              </span>
            </span>
            <span className="row">
              <Button variant={governedEngine ? 'primary' : 'default'} onClick={() => setGovernedEngine(true)}>
                {t('settings.on')}
              </Button>
              <Button variant={!governedEngine ? 'primary' : 'default'} onClick={() => setGovernedEngine(false)}>
                {t('settings.off')}
              </Button>
            </span>
          </div>
        </div>
      </Panel>
    </>
  );
}
