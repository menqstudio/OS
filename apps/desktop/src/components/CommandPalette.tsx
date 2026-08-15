import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../app/store';
import { ALL_ITEMS, navLabel, type RouteId } from '../app/nav';
import { desktop, hasBackend } from '../services/desktop';
import type { SearchResult } from '../domain/entities';

/**
 * The `cmd-dock` — §D's global command palette (⌘K), and the shell's only modal.
 *
 * # Why this file grew accessibility rather than features
 *
 * It worked, and it was unreachable by anything but a mouse and a sighted user. It was a stack of
 * `div`s: no `role="dialog"`, so a screen reader announced nothing when it opened; no focus trap,
 * so `Tab` walked out of the palette and into the page behind it while the scrim still covered the
 * screen; no focus restoration, so closing it dropped the keyboard at the top of the document
 * instead of back on the control that opened it; and the result rows were plain `div`s with
 * `onClick`, so the highlighted row was a CSS class and nothing more — `aria-activedescendant` is
 * what actually tells a screen reader which row `Enter` will take.
 *
 * That mattered more here than on an ordinary panel, because this is the surface §D nominates as
 * the keyboard route to all 23 pages. A keyboard-only owner is exactly the person it was built for
 * and exactly the person it did not serve.
 *
 * The interaction pattern is the ARIA combobox: one focusable input owning a `listbox` it never
 * gives focus to, with the active row named by `aria-activedescendant`. Focus therefore stays in
 * the input the whole time, which is also why the `Tab` trap is a refusal rather than a cycle —
 * there is nowhere else inside to go, and the point is that there is nowhere OUTSIDE to go either.
 *
 * Everything above this line is behaviour that was already correct and is unchanged: ⌘K/Ctrl+K,
 * `Escape`, the debounced entity search with its stale-response guard, and deep-linking through
 * `openEntity`.
 */
export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, setRoute, openEntity, lang, t } = useApp();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [entities, setEntities] = useState<SearchResult[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  /** The element that had focus when the palette opened, so closing can hand it back. */
  const openerRef = useRef<HTMLElement | null>(null);
  /** Stable ids: `aria-controls` and `aria-activedescendant` are id references, and two palettes
   *  in one document (a test rendering twice, a future split view) must not collide. */
  const listId = useRef(`palette-list-${Math.random().toString(36).slice(2)}`).current;
  const optionId = (idx: number) => `${listId}-opt-${idx}`;

  // global Cmd/Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen(true);
      }
      if (e.key === 'Escape') setPaletteOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setPaletteOpen]);

  useEffect(() => {
    if (paletteOpen) {
      setQ('');
      setActive(0);
      setEntities([]);
      // Remembered BEFORE focus moves. Restoring the opener is what makes ⌘K reversible for a
      // keyboard user: open, change your mind, Escape, and carry on from where you were.
      openerRef.current = (document.activeElement as HTMLElement | null) ?? null;
      setTimeout(() => inputRef.current?.focus(), 0);
      return;
    }
    const opener = openerRef.current;
    openerRef.current = null;
    opener?.focus?.();
  }, [paletteOpen]);

  // Nav matches — the original palette behaviour, kept intact.
  const navResults = useMemo(() => {
    // navLabel, not t(labelKey): a page whose copy lives in its own *.strings.ts catalog
    // must still be findable here by its real name, in the active language.
    const items = ALL_ITEMS.map((i) => ({ ...i, label: navLabel(i, lang, t) }));
    if (!q.trim()) return items;
    const s = q.toLowerCase();
    return items.filter((i) => i.label.toLowerCase().includes(s) || i.id.toLowerCase().includes(s));
  }, [q, lang, t]);

  // Debounced global entity search. Guards against races (stale responses) and
  // against the palette closing / unmounting via a per-effect `cancelled` flag.
  useEffect(() => {
    const query = q.trim();
    if (!query || !paletteOpen || !hasBackend()) {
      setEntities([]);
      return;
    }
    let cancelled = false;
    const handle = window.setTimeout(() => {
      desktop
        .searchAll(query)
        .then((res) => { if (!cancelled) setEntities(res); })
        .catch(() => { if (!cancelled) setEntities([]); });
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [q, paletteOpen]);

  const total = navResults.length + entities.length;

  // Keep the highlighted index within the (possibly shrunk) result set.
  useEffect(() => {
    setActive((a) => (a >= total ? Math.max(0, total - 1) : a));
  }, [total]);

  if (!paletteOpen) return null;

  const go = (idx: number) => {
    if (idx < navResults.length) {
      const item = navResults[idx];
      if (!item) return;
      setRoute(item.id);
    } else {
      const ent = entities[idx - navResults.length];
      if (!ent) return;
      // Deep-link: land on the screen AND open the specific item.
      openEntity(ent.route as RouteId, ent.kind, ent.id);
    }
    setPaletteOpen(false);
  };

  const onKeyDown: React.KeyboardEventHandler = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, total - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Home') { e.preventDefault(); setActive(0); }
    else if (e.key === 'End') { e.preventDefault(); setActive(Math.max(0, total - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); go(active); }
    // The trap. The input is the only focusable thing inside a scrim that covers the page, so
    // Tab has nowhere legitimate to go — and letting it leave puts the keyboard behind a modal
    // it cannot see past. Refuse, and stay.
    else if (e.key === 'Tab') { e.preventDefault(); }
  };

  return (
    <div className="palette-scrim" onClick={() => setPaletteOpen(false)}>
      <div
        ref={panelRef}
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label={t('top.command')}
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={q}
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          // The active row is NAMED, not merely highlighted. Without this the palette announces
          // the typed text and nothing about what Enter is aimed at.
          aria-activedescendant={total > 0 ? optionId(active) : undefined}
          aria-label={t('palette.placeholder')}
          placeholder={t('palette.placeholder')}
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={onKeyDown}
        />
        <div className="palette-list" id={listId} role="listbox" aria-label={t('top.command')}>
          {navResults.map((item, idx) => (
            <div
              key={item.id}
              id={optionId(idx)}
              role="option"
              aria-selected={idx === active}
              className={`palette-item ${idx === active ? 'active' : ''}`}
              onMouseEnter={() => setActive(idx)}
              onClick={() => go(idx)}
            >
              <span className="nav-ico">{item.icon}</span>
              <span>{item.label}</span>
              <span className="top-spacer" />
              <span className="muted" style={{ fontSize: 11 }}>{t('palette.navigate')}</span>
            </div>
          ))}

          {entities.length > 0 && (
            <div className="palette-section-label" role="presentation">{t('palette.results')}</div>
          )}
          {entities.map((ent, i) => {
            const idx = navResults.length + i;
            return (
              <div
                key={`${ent.kind}:${ent.id}`}
                id={optionId(idx)}
                role="option"
                aria-selected={idx === active}
                className={`palette-item ${idx === active ? 'active' : ''}`}
                onMouseEnter={() => setActive(idx)}
                onClick={() => go(idx)}
              >
                <span className="badge badge--neutral" style={{ fontSize: 10 }}>{ent.kind}</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ent.title}</span>
                <span className="top-spacer" />
                {ent.subtitle && <span className="muted" style={{ fontSize: 11 }}>{ent.subtitle}</span>}
              </div>
            );
          })}

          {total === 0 && <div className="palette-item muted" role="presentation">{t('state.empty')}</div>}
        </div>
      </div>
    </div>
  );
}
