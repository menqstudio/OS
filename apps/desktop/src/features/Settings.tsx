import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, Skeleton, ErrorState } from '../components/ui';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Lang, Theme } from '../domain/enums';

export function Settings() {
  const { t, theme, toggleTheme, lang, setLang } = useApp();

  const selectTheme = (value: Theme) => {
    if (value !== theme) toggleTheme();
  };

  // Read-only, HONEST view of the provider the backend actually resolved. The
  // provider is chosen by the backend environment (fail-closed policy in ai.rs)
  // — there is no client-side toggle that could route turns through the wall.
  const ai = useAsync(() => desktop.aiStatus(), []);

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

      <Panel title={t('settings.aiProvider')}>
        <div className="stack">
          <span className="muted" style={{ fontSize: 12, maxWidth: 480 }}>
            {t('settings.aiProviderHint')}
          </span>

          {!hasBackend() && <span className="muted">{t('settings.aiProviderUnavailable')}</span>}
          {hasBackend() && (
            <>
              {ai.loading && ai.data === null && <Skeleton rows={2} />}
              {ai.error && <ErrorState message={ai.error} onRetry={ai.reload} />}
              {ai.data && (
                <>
                  <div className="list-row">
                    <span>
                      {ai.data.provider}
                      {ai.data.model && (
                        <span className="muted" style={{ display: 'block', fontSize: 12, marginTop: 2 }}>
                          {ai.data.model}
                        </span>
                      )}
                    </span>
                    <span className="row">
                      <Badge tone={ai.data.governed ? 'success' : 'danger'}>
                        {ai.data.governed ? t('settings.governed') : t('settings.ungoverned')}
                      </Badge>
                      <Badge tone={ai.data.ready ? 'success' : 'warning'}>
                        {ai.data.ready ? t('settings.aiProviderReady') : t('settings.aiProviderNotReady')}
                      </Badge>
                    </span>
                  </div>
                  {ai.data.detail && (
                    <span className="muted" style={{ fontSize: 12, maxWidth: 480 }}>
                      {ai.data.detail}
                    </span>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </Panel>
    </>
  );
}
