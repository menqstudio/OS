import React from 'react';
import './layout.css';
import { useApp } from '../app/store';
import { NAV } from '../app/nav';
import type { Lang } from '../domain/enums';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

export function Shell({ children }: { children: React.ReactNode }) {
  const { route, setRoute, theme, toggleTheme, lang, setLang, setPaletteOpen, t } = useApp();

  // Real badge counts from the backend; absent (0) when no backend is connected.
  const approvalsState = useAsync(() => desktop.listApprovals(), []);
  const notifsState = useAsync(() => desktop.listNotifications(), []);
  const pendingApprovals = (approvalsState.data ?? []).filter((a) => a.status === 'pending').length;
  const unread = (notifsState.data ?? []).filter((n) => n.readAt === null).length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div>
            <div className="brand-name">{t('app.name')}</div>
            <div className="brand-sub">{t('app.tagline')}</div>
          </div>
        </div>
        {NAV.map((group) => (
          <div key={group.labelKey}>
            <div className="nav-group-label">{t(group.labelKey)}</div>
            {group.items.map((item) => (
              <button
                key={item.id}
                className={`nav-item ${route === item.id ? 'active' : ''}`}
                onClick={() => setRoute(item.id)}
              >
                <span className="nav-ico">{item.icon}</span>
                <span>{t(item.labelKey)}</span>
              </button>
            ))}
          </div>
        ))}
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="searchbtn" onClick={() => setPaletteOpen(true)}>
            <span>⌕</span>
            <span>{t('top.search')}</span>
          </button>
          <div className="top-spacer" />
          <select
            className="lang-select"
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            title={t('settings.language')}
          >
            {(Object.keys(languageNames) as Lang[]).map((l) => (
              <option key={l} value={l}>{languageNames[l]}</option>
            ))}
          </select>
          <button className="icon-btn" onClick={toggleTheme} title={t('top.theme')}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <button className="icon-btn" onClick={() => setRoute('approvals')} title={t('top.approvals')}>
            🛡{pendingApprovals > 0 && <span className="dot">{pendingApprovals}</span>}
          </button>
          <button className="icon-btn" onClick={() => setRoute('notifications')} title={t('top.notifications')}>
            🔔{unread > 0 && <span className="dot">{unread}</span>}
          </button>
          <span className="avatar" style={{ width: 34, height: 34 }}>G</span>
        </header>

        <main className="content">
          <div className="content-inner">
            {!hasBackend() && <div className="proto-banner">◍ {t('state.prototype')}</div>}
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
