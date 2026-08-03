import React, { useCallback, useEffect, useRef, useState } from 'react';
import './ui.css';
import { statusTone, type Tone } from '../domain/enums';
import { statusLabel } from '../domain/statusLabels';
import type { AsyncState } from '../hooks/useAsync';
import { hasBackend } from '../services/desktop';
import { useApp, useAppOptional } from '../app/store';

export function Card({ children, className = '', style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return <div className={`card ${className}`} style={style}>{children}</div>;
}

export function Panel({ title, actions, children }: { title?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card>
      <div className="panel">
        {(title || actions) && (
          <div className="panel-head">
            {title && <div className="panel-title">{title}</div>}
            {actions}
          </div>
        )}
        {children}
      </div>
    </Card>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <div className="page-title">{title}</div>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {actions}
    </div>
  );
}

type BtnVariant = 'default' | 'primary' | 'danger' | 'ghost';
export function Button({ children, variant = 'default', small, onClick, title, type = 'button', disabled }:
  { children: React.ReactNode; variant?: BtnVariant; small?: boolean; onClick?: () => void; title?: string; type?: 'button' | 'submit'; disabled?: boolean }) {
  const cls = variant === 'default' ? '' : `btn--${variant}`;
  return <button type={type} title={title} disabled={disabled} className={`btn ${cls} ${small ? 'btn--sm' : ''}`} onClick={onClick}>{children}</button>;
}

export function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: Tone }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const app = useAppOptional();
  const tone = statusTone[status] ?? 'neutral';
  return <Badge tone={tone}>{statusLabel(status, app?.lang ?? 'en')}</Badge>;
}

export function EmptyState({ title, hint, glyph = '◍' }: { title: string; hint?: string; glyph?: string }) {
  return (
    <div className="empty">
      <div className="empty-glyph">{glyph}</div>
      <div className="empty-title">{title}</div>
      {hint && <div className="muted" style={{ marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

export function Avatar({ name }: { name: string }) {
  return <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span>{children}</span>
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 18, width: `${90 - i * 8}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry, retryLabel }: { message: string; onRetry?: () => void; retryLabel?: string }) {
  const { t } = useApp();
  // No desktop backend at all (e.g. browser preview): every screen — including
  // those that render ErrorState directly instead of through <Async> — shows the
  // same calm offline state rather than an alarming red backend error.
  if (!hasBackend()) {
    return <EmptyState glyph="◍" title={t('state.offline')} hint={t('state.offlineHint')} />;
  }
  return (
    <div className="empty">
      <div className="empty-glyph" style={{ color: 'var(--menq-color-danger)' }}>⚠</div>
      <div className="empty-title">Couldn’t load from the backend</div>
      <div className="muted" style={{ marginTop: 4, maxWidth: 460, marginInline: 'auto' }}>{message}</div>
      {onRetry && <div style={{ marginTop: 12 }}><Button small onClick={onRetry}>{retryLabel ?? t('action.retry')}</Button></div>}
    </div>
  );
}

/** Uniform loading / error / empty / populated rendering around a list command. */
export function Async<T>({
  state,
  emptyTitle = 'Nothing here yet',
  emptyHint,
  children,
}: {
  state: AsyncState<T[]>;
  emptyTitle?: string;
  emptyHint?: string;
  children: (data: T[]) => React.ReactNode;
}) {
  const { t } = useApp();
  if (state.loading && state.data === null) return <Skeleton rows={4} />;
  if (state.error) {
    // No desktop backend at all (e.g. browser preview): show a calm offline
    // state, not the alarming red error meant for real backend failures.
    if (!hasBackend()) {
      return <EmptyState glyph="◍" title={t('state.offline')} hint={t('state.offlineHint')} />;
    }
    const denied = /denied|not permitted|permission/i.test(state.error);
    const message = denied ? `${t('state.permissionDenied')}: ${state.error}` : state.error;
    return <ErrorState message={message} onRetry={state.reload} retryLabel={t('action.retry')} />;
  }
  const data = state.data ?? [];
  if (data.length === 0) return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(data)}</>;
}

export function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="form-row">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

export function Input({ ref, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { ref?: React.Ref<HTMLInputElement> }) {
  return <input ref={ref} className="input" {...props} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="textarea" {...props} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="select" {...props} />;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="modal-title">{title}</div>
        {children}
      </div>
    </div>
  );
}

/** Destructive-action confirmation. Blocks a delete/overwrite behind an
 *  explicit second step so nothing irreversible happens on a single click. */
export function ConfirmDialog({
  title, message, confirmLabel, cancelLabel, onConfirm, onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="muted" style={{ marginBottom: 16 }}>{message}</div>
      <div className="form-actions">
        <Button variant="ghost" onClick={onCancel}>{cancelLabel}</Button>
        <Button variant="danger" onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </Modal>
  );
}

/* ───────────────────────────────────────────────────────────────────────────
 * Phase-4 component-library primitives (G1–G6). Presentational and locale-
 * neutral: every label is passed in as a prop (matching Modal / EmptyState /
 * Field), so none of these touch `useApp()` or the Tauri IPC layer. Each covers
 * the standard §D concerns — role/aria, keyboard, non-color signal, and
 * prefers-reduced-motion — through `ui.css`.
 * ─────────────────────────────────────────────────────────────────────────── */

/** Live `prefers-reduced-motion` reader for JS-driven motion. SSR-/test-safe:
 *  returns `false` when `matchMedia` is unavailable (CSS still self-guards). */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduced(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduced;
}

/** Integer count-up toward `target`. Snaps instantly when `animate` is false so
 *  reduced-motion users (and non-numeric tiles) get the final value at once. */
function useCountUp(target: number, animate: boolean): number {
  const [value, setValue] = useState(animate ? 0 : target);
  useEffect(() => {
    if (!animate) { setValue(target); return; }
    let raf = 0;
    const start = performance.now();
    const dur = 600;
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / dur);
      setValue(Math.round(target * p));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, animate]);
  return value;
}

/** Roving-focus keyboard handler over `[data-roving]` descendants (mirrors the
 *  Shell nav/dock pattern). Purely moves DOM focus; never activates. */
function rovingKeydown(
  e: React.KeyboardEvent<HTMLElement>,
  orientation: 'vertical' | 'horizontal' | 'both',
) {
  const next = orientation === 'vertical' ? ['ArrowDown']
    : orientation === 'horizontal' ? ['ArrowRight'] : ['ArrowDown', 'ArrowRight'];
  const prev = orientation === 'vertical' ? ['ArrowUp']
    : orientation === 'horizontal' ? ['ArrowLeft'] : ['ArrowUp', 'ArrowLeft'];
  const isNext = next.includes(e.key);
  const isPrev = prev.includes(e.key);
  if (!isNext && !isPrev && e.key !== 'Home' && e.key !== 'End') return;
  const items = Array.from(
    e.currentTarget.querySelectorAll<HTMLElement>('[data-roving]'),
  ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true');
  if (items.length === 0) return;
  const current = items.indexOf(document.activeElement as HTMLElement);
  let idx = current;
  if (isNext) idx = current < 0 ? 0 : (current + 1) % items.length;
  else if (isPrev) idx = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
  else if (e.key === 'Home') idx = 0;
  else if (e.key === 'End') idx = items.length - 1;
  const target = items[idx];
  if (target) { e.preventDefault(); target.focus(); }
}

// ── G1 · DataTable ──────────────────────────────────────────────────────────
export interface Column<T> {
  /** Stable key; also the default cell accessor when no `render` is given. */
  key: string;
  header: React.ReactNode;
  render?: (row: T, index: number) => React.ReactNode;
  /** Right-align numeric columns (tabular-nums), a non-color layout signal. */
  numeric?: boolean;
}

/**
 * Accessible data table. Native `<table>` (implicit `role="table"`) with a
 * caption, `<th scope>` headers, roving row focus (Up/Down/Home/End, Enter or
 * Space activates when `onActivateRow` is set), plus loading (skeleton) and
 * empty variants. Color is never the signal — meaning is text + alignment.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  loading = false,
  emptyTitle = 'Nothing here yet',
  emptyHint,
  emptyGlyph,
  onActivateRow,
  skeletonRows = 4,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  caption: string;
  loading?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  emptyGlyph?: string;
  onActivateRow?: (row: T, index: number) => void;
  skeletonRows?: number;
}) {
  const [focusIdx, setFocusIdx] = useState(0);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTableSectionElement>) => {
    if (rows.length === 0) return;
    const move = (idx: number) => {
      const clamped = Math.max(0, Math.min(rows.length - 1, idx));
      setFocusIdx(clamped);
      e.preventDefault();
      rowRefs.current[clamped]?.focus();
    };
    switch (e.key) {
      case 'ArrowDown': move(focusIdx + 1); break;
      case 'ArrowUp': move(focusIdx - 1); break;
      case 'Home': move(0); break;
      case 'End': move(rows.length - 1); break;
      case 'Enter':
      case ' ':
      case 'Spacebar':
        if (onActivateRow) { e.preventDefault(); onActivateRow(rows[focusIdx], focusIdx); }
        break;
      default: break;
    }
  };

  return (
    <div className="dt-wrap">
      <table className="dt" role="table">
        <caption className="dt-caption">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? 'dt-num' : undefined}>{c.header}</th>
            ))}
          </tr>
        </thead>
        {loading ? (
          <tbody aria-busy="true">
            {Array.from({ length: skeletonRows }).map((_, r) => (
              <tr key={r} className="dt-row dt-row--skeleton">
                {columns.map((c) => (
                  <td key={c.key} className={c.numeric ? 'dt-num' : undefined}>
                    <span className="skeleton" style={{ height: 14, width: `${70 - (r % 3) * 12}%` }} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        ) : rows.length === 0 ? (
          <tbody>
            <tr>
              <td colSpan={columns.length} className="dt-empty-cell">
                <EmptyState title={emptyTitle} hint={emptyHint} glyph={emptyGlyph} />
              </td>
            </tr>
          </tbody>
        ) : (
          <tbody onKeyDown={onKeyDown}>
            {rows.map((row, i) => (
              <tr
                key={rowKey(row, i)}
                ref={(el) => { rowRefs.current[i] = el; }}
                className={`dt-row ${onActivateRow ? 'dt-row--action' : ''}`}
                tabIndex={i === Math.min(focusIdx, rows.length - 1) ? 0 : -1}
                onFocus={() => setFocusIdx(i)}
                onClick={onActivateRow ? () => onActivateRow(row, i) : undefined}
                aria-label={onActivateRow ? caption : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key} className={c.numeric ? 'dt-num' : undefined}>
                    {c.render ? c.render(row, i) : (row as Record<string, React.ReactNode>)[c.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        )}
      </table>
    </div>
  );
}

// ── G2 · Drawer ─────────────────────────────────────────────────────────────
/**
 * Side drawer — a Modal that slides in from an edge. Mirrors `Modal`
 * (`role="dialog"`, `aria-modal="true"`, scrim click closes) and adds what a
 * transient side panel needs: Esc to close, a Tab focus-trap, initial focus on
 * the first focusable inside, and focus restoration to the opener on unmount.
 */
export function Drawer({
  title,
  onClose,
  side = 'right',
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  side?: 'left' | 'right';
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const app = useAppOptional();
  const closeLabel = app ? app.t('action.close') : 'Close';
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useRef(`drawer-${Math.random().toString(36).slice(2)}`).current;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    (focusables()[0] ?? panelRef.current)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) { e.preventDefault(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      opener?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <div
        ref={panelRef}
        className={`drawer drawer--${side}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-head">
          <div className="drawer-title" id={titleId}>{title}</div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={`${closeLabel} ${title}`} title={closeLabel}>
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </div>
    </div>
  );
}

// ── G3 · Rail / RailSection ─────────────────────────────────────────────────
/**
 * Labeled side-rail region — the context/command/group rail pattern as one
 * primitive. Compose `RailSection` children for titled sub-groups.
 *
 * Two renderings, chosen by `variant`:
 * - `'complementary'` (default) — a landmark `<aside role="complementary">` with
 *   an accessible name and an uppercase rail header. Use for a genuine context
 *   rail that should be a navigable landmark.
 * - `'panel'` — a plain `Card`/`.panel` container identical to `Panel` (title as
 *   `.panel-title`, `space-5` padding, NO landmark role). Use when the region is
 *   a list/rail that must adopt the rail model WITHOUT adding another
 *   `complementary` landmark or changing the panel's padding — e.g. the
 *   conversation and command run lists.
 */
export function Rail({
  label,
  side = 'left',
  actions,
  variant = 'complementary',
  children,
}: {
  label: string;
  side?: 'left' | 'right';
  actions?: React.ReactNode;
  variant?: 'complementary' | 'panel';
  children: React.ReactNode;
}) {
  if (variant === 'panel') {
    // Identical markup to `Panel` (Card + .panel, title in .panel-head, children
    // rendered directly) so adopting the rail model changes neither the padding
    // nor the landmark structure.
    return (
      <Card>
        <div className="panel">
          {(label || actions) && (
            <div className="panel-head">
              {label && <div className="panel-title">{label}</div>}
              {actions}
            </div>
          )}
          {children}
        </div>
      </Card>
    );
  }
  return (
    <aside className={`rail rail--${side}`} role="complementary" aria-label={label}>
      {(label || actions) && (
        <div className="rail-head">
          <span className="rail-title">{label}</span>
          {actions}
        </div>
      )}
      <div className="rail-body">{children}</div>
    </aside>
  );
}

export function RailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rail-section" aria-label={title}>
      <div className="rail-section-title">{title}</div>
      <div className="rail-section-body">{children}</div>
    </section>
  );
}

// ── G4 · TileGroup / StatTile ───────────────────────────────────────────────
/**
 * Roving container for a row/grid of `StatTile`s. Arrow keys (both axes) plus
 * Home/End move focus between the actionable tiles; exactly one tile is in the
 * tab order at a time.
 */
export function TileGroup({ label, children }: { label: string; children: React.ReactNode }) {
  const [focus, setFocus] = useState(0);
  const items = React.Children.toArray(children);
  return (
    <div
      className="tile-group grid grid-3"
      role="group"
      aria-label={label}
      onKeyDown={(e) => rovingKeydown(e, 'both')}
    >
      {items.map((child, i) =>
        React.isValidElement(child)
          ? React.cloneElement(child as React.ReactElement<StatTileProps>, {
            key: i,
            tabIndex: i === focus ? 0 : -1,
            onFocusCapture: () => setFocus(i),
          })
          : child,
      )}
    </div>
  );
}

interface StatTileProps {
  glyph: string;
  value: React.ReactNode;
  label: string;
  hint?: string;
  /** Animate a numeric `value` from 0 (respects reduced-motion). */
  countUp?: boolean;
  /** Renders the tile as a link/button and shows a directional arrow. */
  onActivate?: () => void;
  tabIndex?: number;
  onFocusCapture?: () => void;
}

/**
 * Stat tile — glyph + value + label, promoted from Home's bespoke `.stat`.
 * When `onActivate` is set it becomes a keyboard-operable link (arrow inside a
 * `TileGroup`) with a trailing "→"; the glyph and label carry meaning without
 * relying on color.
 */
export function StatTile({
  glyph, value, label, hint, countUp = false, onActivate, tabIndex, onFocusCapture,
}: StatTileProps) {
  const reduced = usePrefersReducedMotion();
  const numeric = typeof value === 'number';
  const counted = useCountUp(numeric ? (value as number) : 0, countUp && numeric && !reduced);
  const shown = countUp && numeric ? counted : value;

  const inner = (
    <>
      <span className="tile-glyph" aria-hidden="true">{glyph}</span>
      <span className="tile-value">{shown}</span>
      <span className="tile-label">{label}</span>
      {hint && <span className="tile-hint muted">{hint}</span>}
    </>
  );

  if (onActivate) {
    return (
      <button
        type="button"
        data-roving
        className="tile tile--link"
        tabIndex={tabIndex}
        onClick={onActivate}
        onFocus={onFocusCapture}
      >
        {inner}
        <span className="tile-arrow" aria-hidden="true">→</span>
      </button>
    );
  }
  return <div className="tile">{inner}</div>;
}

// ── G5 · Mark / LiveMark ────────────────────────────────────────────────────
/**
 * The "Br·PS" wordmark with its square glyph (promoted from Shell's brand).
 *
 * `responsive` honours the collapsed-sidebar rule: at ≤900px the text (word +
 * sub) is hidden and only the square glyph remains, exactly like the sidebar
 * collapses its labels — so Shell can adopt this without breaking the narrow
 * layout. The glyph keeps a `title` so the collapsed mark stays identifiable.
 */
export function Mark({
  word = 'Br·PS', sub, glyph = 'B', responsive = false,
}: { word?: string; sub?: string; glyph?: string; responsive?: boolean }) {
  return (
    <span className={`mark ${responsive ? 'mark--responsive' : ''}`}>
      <span className="mark-glyph" aria-hidden="true" title={responsive ? word : undefined}>{glyph}</span>
      <span className="mark-text">
        <span className="mark-word">{word}</span>
        {sub && <span className="mark-sub">{sub}</span>}
      </span>
    </span>
  );
}

/**
 * Live "Br·PS" mark — the wordmark with a status dot that pulses only when
 * `state="live"` (and reduced-motion is off). The state word ("Live" /
 * "Connecting" / "Offline") is the non-color signal; the color merely echoes it.
 */
export function LiveMark({
  state = 'live',
  label,
  word = 'Br·PS',
}: {
  state?: 'live' | 'connecting' | 'offline';
  label?: string;
  word?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const fallback = state === 'live' ? 'Live' : state === 'connecting' ? 'Connecting' : 'Offline';
  const text = label ?? fallback;
  return (
    <span className={`livemark livemark--${state} ${reduced ? 'livemark--still' : ''}`}>
      <span className="livemark-dot" aria-hidden="true" />
      <span className="livemark-word">{word}</span>
      <span className="livemark-state">{text}</span>
    </span>
  );
}

// ── G6 · InlineAlert ────────────────────────────────────────────────────────
const ALERT_GLYPH: Record<string, string> = {
  info: 'ℹ', success: '✓', warning: '⚠', danger: '⚠',
};

/**
 * Inline alert strip. `danger` announces via `role="alert"` (assertive); the
 * calmer tones use `role="status"` (polite). A leading glyph carries the tone
 * without relying on color alone.
 */
export function InlineAlert({
  tone = 'info',
  title,
  children,
  glyph,
}: {
  tone?: 'info' | 'success' | 'warning' | 'danger';
  title?: string;
  children?: React.ReactNode;
  glyph?: string;
}) {
  return (
    <div className={`inline-alert inline-alert--${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <span className="inline-alert-glyph" aria-hidden="true">{glyph ?? ALERT_GLYPH[tone]}</span>
      <div className="inline-alert-body">
        {title && <div className="inline-alert-title">{title}</div>}
        {children && <div className="inline-alert-msg">{children}</div>}
      </div>
    </div>
  );
}
