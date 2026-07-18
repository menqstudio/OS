import { useApp } from '../app/store';
import { PageHeader, Panel, Button } from '../components/ui';
import { languageNames } from '../i18n';
import type { Lang, Theme } from '../domain/enums';

export function Settings() {
  const { t, theme, toggleTheme, lang, setLang } = useApp();

  const selectTheme = (value: Theme) => {
    if (value !== theme) toggleTheme();
  };

  const sections = ['Profile', 'AI providers', 'Permissions', 'Notifications', 'Storage', 'Backup', 'Security', 'Diagnostics'];

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
        </div>
      </Panel>

      <div style={{ marginTop: 16 }}>
        <Panel title="Preferences">
          <div className="stack">
            {sections.map((s) => (
              <div key={s} className="list-row">
                <span>{s}</span>
                <span className="muted">Prototype</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
