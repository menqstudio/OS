import React, { useCallback, useState } from 'react';
import './layout.css';
import { useApp } from '../app/store';
import { NAV } from '../app/nav';
import type { Lang } from '../domain/enums';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { AmbientLayer, Mark, useIgnition } from './Ambient';

/**
 * Shell — the BroPS AI-OS app frame, ported from the `brops-aios` design mockup.
 *
 * A luminous side rail (brand lockup + grouped nav + control footer) beside the
 * routed stage, over the fixed ambient layer, behind the power-on gate. It keeps
 * every load-bearing behaviour of the previous shell: real backend badge counts,
 * i18n, theme + language switching, the command palette, and full keyboard a11y
 * (skip link target, roving-tabindex nav). Only the visual language changed.
 */

/**
 * Roving-tabindex keyboard handler for the nav rail: Arrow keys plus Home/End
 * move DOM focus between the `[data-roving]` items. Purely additive — click and
 * Tab behaviour are unchanged; it never navigates on its own.
 */
function useRovingKeydown(orientation: 'vertical' | 'horizontal') {
  return useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      const nextKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
      const prevKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
      if (e.key !== nextKey && e.key !== prevKey && e.key !== 'Home' && e.key !== 'End') return;
      const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[data-roving]')).filter(
        (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true',
      );
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
  const { gateLift, powerOn, gateMarkRef } = useIgnition();

  // Real badge counts from the backend; absent (0) when no backend is connected.
  const approvalsState = useAsync(() => desktop.listApprovals(), []);
  const notifsState = useAsync(() => desktop.listNotifications(), []);
  const pendingApprovals = (approvalsState.data ?? []).filter((a) => a.status === 'pending').length;
  const unread = (notifsState.data ?? []).filter((n) => n.readAt === null).length;
  const badgeFor = (id: string): number =>
    id === 'approvals' ? pendingApprovals : id === 'notifications' ? unread : 0;

  const onNavKeyDown = useRovingKeydown('vertical');
  const onDockKeyDown = useRovingKeydown('horizontal');
  const [dockFocus, setDockFocus] = useState(0);

  return (
    <>
      <AmbientLayer />

      {/* power-on gate — press the mark or Space to ignite the OS */}
      {!gateLift && (
        <div id="gate" role="dialog" aria-label={t('app.name')}>
          <button type="button" className="lockup" onClick={powerOn}>
            <b>Br</b>
            <Mark state="" size={0} style={{ width: '1em', height: '1em' }} />
            <b>PS</b>
          </button>
          <span className="hint" aria-hidden="true">
            <span className="kbd">Space</span>
          </span>
          {/* the gate's boot animation is applied to this ref by useIgnition */}
          <span ref={gateMarkRef} style={{ display: 'none' }} />
        </div>
      )}

      <div className="app">
        <aside className="side">
          <a
            className="brand"
            href="#home"
            onClick={(e) => {
              e.preventDefault();
              setRoute('home');
            }}
          >
            <b>Br</b>
            <Mark state="live" size={0} style={{ width: '1em', height: '1em' }} />
            <b>PS</b>
          </a>

          <nav className="nav" aria-label={t('a11y.primaryNav')} onKeyDown={onNavKeyDown}>
            {NAV.map((group) => {
              const labelId = `nav-group-${group.labelKey}`;
              return (
                <div key={group.labelKey} role="group" aria-labelledby={labelId}>
                  <h5 id={labelId}>{t(group.labelKey)}</h5>
                  {group.items.map((item) => {
                    const active = route === item.id;
                    const badge = badgeFor(item.id);
                    const label = badge > 0 ? `${t(item.labelKey)} (${badge})` : t(item.labelKey);
                    return (
                      <a
                        key={item.id}
                        href={`#${item.id}`}
                        data-roving
                        className={active ? 'on' : ''}
                        aria-current={active ? 'page' : undefined}
                        aria-label={badge > 0 ? label : undefined}
                        tabIndex={active ? 0 : -1}
                        onClick={(e) => {
                          e.preventDefault();
                          setRoute(item.id);
                        }}
                      >
                        <i aria-hidden="true">{item.icon}</i>
                        <span>{t(item.labelKey)}</span>
                        {badge > 0 && (
                          <span className="nav-badge" aria-hidden="true">
                            {badge}
                          </span>
                        )}
                      </a>
                    );
                  })}
                </div>
              );
            })}
          </nav>

          <div className="side-foot" role="toolbar" aria-label={t('a11y.toolbar')} onKeyDown={onDockKeyDown}>
            <button
              type="button"
              data-roving
              tabIndex={dockFocus === 0 ? 0 : -1}
              onFocus={() => setDockFocus(0)}
              className="iconbtn"
              onClick={() => setPaletteOpen(true)}
              aria-label={t('top.command')}
              title={t('top.command')}
            >
              <span aria-hidden="true">⌘</span>
            </button>
            <button
              type="button"
              data-roving
              tabIndex={dockFocus === 1 ? 0 : -1}
              onFocus={() => setDockFocus(1)}
              className="iconbtn"
              onClick={toggleTheme}
              aria-label={t('top.theme')}
              title={t('top.theme')}
            >
              <span aria-hidden="true">{theme === 'dark' ? '☀' : '☾'}</span>
            </button>
            <select
              className="lang-select"
              value={lang}
              onChange={(e) => setLang(e.target.value as Lang)}
              aria-label={t('settings.language')}
              title={t('settings.language')}
            >
              {(Object.keys(languageNames) as Lang[]).map((l) => (
                <option key={l} value={l}>
                  {languageNames[l]}
                </option>
              ))}
            </select>
            <span className="micro side-ver">MENQ OS · v0.9</span>
          </div>
        </aside>

        <main id="main-content" className="stage" tabIndex={-1}>
          {!hasBackend() && <div className="proto-banner">◍ {t('state.prototype')}</div>}
          {children}
        </main>
      </div>
    </>
  );
}
