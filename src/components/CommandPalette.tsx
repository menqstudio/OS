import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../app/store';
import { ALL_ITEMS, type RouteId } from '../app/nav';
import { desktop, hasBackend } from '../services/desktop';
import type { SearchResult } from '../domain/entities';

export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, setRoute, t } = useApp();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [entities, setEntities] = useState<SearchResult[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

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
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [paletteOpen]);

  // Nav matches — the original palette behaviour, kept intact.
  const navResults = useMemo(() => {
    const items = ALL_ITEMS.map((i) => ({ ...i, label: t(i.labelKey) }));
    if (!q.trim()) return items;
    const s = q.toLowerCase();
    return items.filter((i) => i.label.toLowerCase().includes(s) || i.id.toLowerCase().includes(s));
  }, [q, t]);

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
      setRoute(ent.route as RouteId);
    }
    setPaletteOpen(false);
  };

  const onKeyDown: React.KeyboardEventHandler = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, total - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); go(active); }
  };

  return (
    <div className="palette-scrim" onClick={() => setPaletteOpen(false)}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={q}
          placeholder={t('palette.placeholder')}
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={onKeyDown}
        />
        <div className="palette-list">
          {navResults.map((item, idx) => (
            <div
              key={item.id}
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
            <div className="palette-section-label">{t('palette.results')}</div>
          )}
          {entities.map((ent, i) => {
            const idx = navResults.length + i;
            return (
              <div
                key={`${ent.kind}:${ent.id}`}
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

          {total === 0 && <div className="palette-item muted">{t('state.empty')}</div>}
        </div>
      </div>
    </div>
  );
}
