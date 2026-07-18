import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../app/store';
import { ALL_ITEMS } from '../app/nav';

export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, setRoute, t } = useApp();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
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
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [paletteOpen]);

  const results = useMemo(() => {
    const items = ALL_ITEMS.map((i) => ({ ...i, label: t(i.labelKey) }));
    if (!q.trim()) return items;
    const s = q.toLowerCase();
    return items.filter((i) => i.label.toLowerCase().includes(s) || i.id.toLowerCase().includes(s));
  }, [q, t]);

  if (!paletteOpen) return null;

  const go = (idx: number) => {
    const item = results[idx];
    if (!item) return;
    setRoute(item.id);
    setPaletteOpen(false);
  };

  const onKeyDown: React.KeyboardEventHandler = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
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
          {results.map((item, idx) => (
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
          {results.length === 0 && <div className="palette-item muted">{t('state.empty')}</div>}
        </div>
      </div>
    </div>
  );
}
