import React, { useCallback, useEffect, useState } from 'react';
import './layout.css';
import { useApp } from '../app/store';
import { NAV, navLabel } from '../app/nav';
import type { Lang } from '../domain/enums';
import { languageNames } from '../i18n';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { AmbientLayer, Mark, useIgnition } from './Ambient';
import { NavIcon } from './NavIcons';

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
  // On narrow screens the side rail is an off-canvas drawer; this toggles it.
  const [navOpen, setNavOpen] = useState(false);
  /**
   * Right-click menu.
   *
   * It used to carry one item — *Open in new window* — and suppress the native menu everywhere
   * except inside a text field. So right-clicking a chat reply, a file name, an error message or
   * anything else selectable offered no **Copy**, and the app felt broken in the one place every
   * desktop app behaves the same way.
   *
   * The menu is now the standard set, and which items appear is decided by what was actually
   * clicked rather than by a fixed list: Copy and Cut only when there is something to copy or cut,
   * Paste only in a field that can receive it. An item that cannot do anything is not shown, which
   * is more useful than one that is shown greyed out and less misleading than one that is shown
   * live and silently does nothing.
   */
  const [ctxMenu, setCtxMenu] = useState<{
    x: number; y: number; editable: boolean; selection: string;
  } | null>(null);
  const onAppContextMenu = (e: React.MouseEvent) => {
    const el = e.target as HTMLElement;
    const field = el.closest<HTMLElement>('input, textarea, [contenteditable="true"]');
    e.preventDefault();
    setCtxMenu({
      x: e.clientX,
      y: e.clientY,
      editable: field !== null && !(field as HTMLInputElement).readOnly,
      selection: (window.getSelection()?.toString() ?? '').trim(),
    });
  };
  /**
   * A message when opening a second window fails, shown instead of swallowed.
   *
   * `open_window` can refuse for a real reason — the concurrent-window cap is eight — and the only
   * evidence used to be a line in a console the packaged app has no way to show. "It does nothing"
   * and "it refused and told nobody" look identical from the outside, and only one of them is a bug.
   */
  const [windowError, setWindowError] = useState<string | null>(null);

  /**
   * The clipboard actions, run against the real selection after the menu closes.
   *
   * `execCommand` is deprecated and is still the only thing that acts on the document's own
   * selection in a webview without a permission prompt; `navigator.clipboard.readText()` is the
   * paste half, because `execCommand('paste')` is blocked for security in every modern engine.
   * Focus is restored first — the menu button took it when it was clicked, and a copy with nothing
   * selected copies nothing.
   */
  const runCtx = useCallback((action: 'copy' | 'cut' | 'paste' | 'selectAll') => {
    const menu = ctxMenu;
    setCtxMenu(null);
    if (!menu) return;
    const active = document.activeElement as HTMLElement | null;
    if (active && 'blur' in active) active.blur();
    window.setTimeout(() => {
      if (action === 'paste') {
        void navigator.clipboard.readText().then((text) => {
          const el = document.activeElement as HTMLInputElement | HTMLTextAreaElement | null;
          if (el && ('value' in el)) {
            const start = el.selectionStart ?? el.value.length;
            const end = el.selectionEnd ?? start;
            el.value = el.value.slice(0, start) + text + el.value.slice(end);
            // React tracks the value on the DOM node; without an input event the state behind a
            // controlled field never learns about the paste and the next render wipes it.
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.selectionStart = el.selectionEnd = start + text.length;
          }
        }).catch(() => { /* clipboard unreadable — nothing to paste, and nothing to report */ });
        return;
      }
      document.execCommand(action === 'selectAll' ? 'selectAll' : action);
    }, 0);
  }, [ctxMenu]);

  // Escape closes the transient overlays (nav drawer, context menu).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setNavOpen(false); setCtxMenu(null); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

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

      <div className="app" onContextMenu={onAppContextMenu}>
        {/* Narrow-screen nav toggle + scrim (hidden ≥860px via CSS) so the rail is
            reachable on small windows instead of being stuck off-canvas. */}
        <button
          type="button"
          className="nav-toggle"
          aria-label={t('a11y.primaryNav')}
          aria-expanded={navOpen}
          onClick={() => setNavOpen((o) => !o)}
        >
          <span aria-hidden="true">{navOpen ? '✕' : '☰'}</span>
        </button>
        {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />}
        <aside className={`side${navOpen ? ' open' : ''}`}>
          <a
            className="brand"
            href="#home"
            onClick={(e) => {
              e.preventDefault();
              setRoute('home');
              setNavOpen(false);
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
                    // navLabel, not t(labelKey): a page may own its trilingual copy in its own
                    // *.strings.ts catalog instead of the shared dictionaries.
                    const name = navLabel(item, lang, t);
                    const label = badge > 0 ? `${name} (${badge})` : name;
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
                          setNavOpen(false);
                        }}
                      >
                        <i aria-hidden="true">
                          <NavIcon id={item.id} />
                        </i>
                        <span>{name}</span>
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
          {/* Outside the Tauri runtime there is NO mock/fixture layer: `services/desktop.ts`
              maps every IPC name to a registered `#[tauri::command]`, so each call simply
              rejects and each panel renders its own error state. The banner says exactly
              that — it must never advertise mock data the build does not contain. */}
          {!hasBackend() && <div className="proto-banner" role="status">◍ {t('state.prototype')}</div>}
          {/* keyed on route so the stage replays a soft page-enter on each view change */}
          <div key={route} className="stage-enter">
            {children}
          </div>
        </main>
      </div>

      {ctxMenu && (
        <>
          <div
            className="ctx-scrim"
            onClick={() => setCtxMenu(null)}
            onContextMenu={(e) => { e.preventDefault(); setCtxMenu(null); }}
          />
          <div className="ctx-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }} role="menu">
            {ctxMenu.selection !== '' && (
              <button type="button" role="menuitem" onClick={() => runCtx('copy')}>
                {t('action.copy')}
              </button>
            )}
            {ctxMenu.selection !== '' && ctxMenu.editable && (
              <button type="button" role="menuitem" onClick={() => runCtx('cut')}>
                {t('action.cut')}
              </button>
            )}
            {ctxMenu.editable && (
              <button type="button" role="menuitem" onClick={() => runCtx('paste')}>
                {t('action.paste')}
              </button>
            )}
            <button type="button" role="menuitem" onClick={() => runCtx('selectAll')}>
              {t('action.selectAll')}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                // The failure used to go to `console.error`, which in a packaged desktop app is a
                // place nobody can look — so "it just does nothing" was the only symptom available.
                // It reports now.
                void desktop.openWindow(route).catch((err) => {
                  setWindowError(err instanceof Error ? err.message : String(err));
                });
                setCtxMenu(null);
              }}
            >
              {t('action.openNewWindow')}
            </button>
          </div>
        </>
      )}

      {windowError !== null && (
        <div className="inline-alert inline-alert--error ctx-window-error" role="alert">
          <b>{t('action.windowFailed')}</b>
          <span>{windowError}</span>
          <button type="button" onClick={() => setWindowError(null)} aria-label="Dismiss">✕</button>
        </div>
      )}
    </>
  );
}
