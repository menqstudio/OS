import React, { useCallback, useState } from 'react';
import './layout.css';
import { useApp } from '../app/store';
import { NAV } from '../app/nav';
import type { Lang } from '../domain/enums';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Mark } from './ui';

/**
 * Roving-tabindex keyboard handler for a composite widget (the nav list or the
 * toolbar "command dock"). Arrow keys plus Home/End move focus between the
 * elements marked with `data-roving`. Purely additive: it never navigates on
 * its own — click and Tab behaviour are unchanged; only DOM focus moves.
 */
function useRovingKeydown(orientation: 'vertical' | 'horizontal') {
  return useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      const nextKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
      const prevKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
      if (e.key !== nextKey && e.key !== prevKey && e.key !== 'Home' && e.key !== 'End') return;
      const items = Array.from(
        e.currentTarget.querySelectorAll<HTMLElement>('[data-roving]'),
      ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true');
      if (items.length === 0) return;
      const current = items.indexOf(document.activeElement as HTMLElement);
      let next = current;
      if (e.key === nextKey) next = current < 0 ? 0 : (current + 1) % items.length;
      else if (e.key === prevKey) next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = items.length - 1;
      const target = items[next];
      if (target) {
        e.preventDefault();
        target.focus();
      }
    },
    [orientation],
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { route, setRoute, theme, toggleTheme, lang, setLang, setPaletteOpen, t } = useApp();

  // Real badge counts from the backend; absent (0) when no backend is connected.
  const approvalsState = useAsync(() => desktop.listApprovals(), []);
  const notifsState = useAsync(() => desktop.listNotifications(), []);
  const pendingApprovals = (approvalsState.data ?? []).filter((a) => a.status === 'pending').length;
  const unread = (notifsState.data ?? []).filter((n) => n.readAt === null).length;

  const onNavKeyDown = useRovingKeydown('vertical');
  const onDockKeyDown = useRovingKeydown('horizontal');

  // Roving tab stop for the toolbar: exactly one button is tabbable at a time,
  // and it follows the last-focused control. The sidebar uses the active route
  // as its single tab stop, so it needs no separate state.
  const [dockFocus, setDockFocus] = useState(0);

  // Counts are folded into the accessible name so screen readers announce them
  // (the visual badge is decorative and aria-hidden). t() has no interpolation,
  // so the number is appended in a locale-neutral "(n)" form.
  const approvalsLabel = pendingApprovals > 0 ? `${t('top.approvals')} (${pendingApprovals})` : t('top.approvals');
  const notifsLabel = unread > 0 ? `${t('top.notifications')} (${unread})` : t('top.notifications');

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Mark responsive glyph="B" word={t('app.name')} sub={t('app.tagline')} />
        </div>
        <nav className="nav" aria-label={t('a11y.primaryNav')} onKeyDown={onNavKeyDown}>
          {NAV.map((group) => {
            const labelId = `nav-group-${group.labelKey}`;
            return (
              <div key={group.labelKey} role="group" aria-labelledby={labelId}>
                <div className="nav-group-label" id={labelId}>{t(group.labelKey)}</div>
                {group.items.map((item) => {
                  const active = route === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      data-roving
                      className={`nav-item ${active ? 'active' : ''}`}
                      aria-current={active ? 'page' : undefined}
                      tabIndex={active ? 0 : -1}
                      onClick={() => setRoute(item.id)}
                    >
                      <span className="nav-ico" aria-hidden="true">{item.icon}</span>
                      <span>{t(item.labelKey)}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <button type="button" className="searchbtn" onClick={() => setPaletteOpen(true)} title={t('top.command')}>
            <span aria-hidden="true">⌕</span>
            <span>{t('top.search')}</span>
          </button>
          <div className="top-spacer" />
          <select
            className="lang-select"
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            aria-label={t('settings.language')}
            title={t('settings.language')}
          >
            {(Object.keys(languageNames) as Lang[]).map((l) => (
              <option key={l} value={l}>{languageNames[l]}</option>
            ))}
          </select>
          <div className="dock" role="toolbar" aria-label={t('a11y.toolbar')} onKeyDown={onDockKeyDown}>
            <button
              type="button"
              data-roving
              tabIndex={dockFocus === 0 ? 0 : -1}
              onFocus={() => setDockFocus(0)}
              className="icon-btn"
              onClick={toggleTheme}
              aria-label={t('top.theme')}
              title={t('top.theme')}
            >
              <span aria-hidden="true">{theme === 'dark' ? '☀' : '☾'}</span>
            </button>
            <button
              type="button"
              data-roving
              tabIndex={dockFocus === 1 ? 0 : -1}
              onFocus={() => setDockFocus(1)}
              className="icon-btn"
              onClick={() => setRoute('approvals')}
              aria-label={approvalsLabel}
              title={t('top.approvals')}
            >
              <span aria-hidden="true">🛡</span>
              {pendingApprovals > 0 && <span className="dot" aria-hidden="true">{pendingApprovals}</span>}
            </button>
            <button
              type="button"
              data-roving
              tabIndex={dockFocus === 2 ? 0 : -1}
              onFocus={() => setDockFocus(2)}
              className="icon-btn"
              onClick={() => setRoute('notifications')}
              aria-label={notifsLabel}
              title={t('top.notifications')}
            >
              <span aria-hidden="true">🔔</span>
              {unread > 0 && <span className="dot" aria-hidden="true">{unread}</span>}
            </button>
          </div>
          <span
            className="avatar"
            role="img"
            aria-label={t('top.account')}
            title={t('top.account')}
            style={{ width: 34, height: 34 }}
          >G</span>
        </header>

        <main id="main-content" className="content" tabIndex={-1}>
          <div className="content-inner">
            {!hasBackend() && <div className="proto-banner">◍ {t('state.prototype')}</div>}
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
