import React, { useEffect, useRef, type KeyboardEvent } from 'react';
import '../ui.css';
import { EmptyState, usePrefersReducedMotion } from '../ui';
import { STRIP_W, STRIP_H, buildECG, buildLinePath, pointCoords } from './geometry';
import { useApp } from '../../app/store';
import type { Lang } from '../../domain/enums';
import { localize, beatSummary, barSummary, type StrKey } from './Chart.strings';

// Read the active UI language reactively. `useApp()` throws outside an
// `AppProvider` (e.g. in isolated component tests); those callers are treated as
// English so the primitives stay usable standalone. `useApp` calls its own
// hooks before any throw, so hook order is stable across renders either way.
function useLang(): Lang {
  try {
    return useApp().lang;
  } catch {
    return 'en';
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Charts primitive — a reusable, accessible line/beatline chart.
//
// It reuses three patterns already proven in the pages:
//   • deterministic SVG geometry (Activity's ECG strip → charts/geometry.ts),
//   • an accessible one-line summary that the <svg role="img"> is labelled by
//     (Analytics' `an-cap`), and
//   • a <details> data-table fallback so every point is reachable as text
//     (Analytics' `an-table`).
//
// Color is never the signal: a single accent stroke draws the line and meaning
// is carried by the summary text, the point titles, and the table. Loading and
// empty variants are honest states, not fabricated data.
// ─────────────────────────────────────────────────────────────────────────────

export interface BeatPoint {
  /** Text label for this point (row header in the fallback table, dot title). */
  label: string;
  value: number;
}

let seq = 0;

/**
 * Beatline — an accessible deterministic line chart over `data`.
 * - `role="img"` on the SVG, labelled by the visible summary (auto-generated if
 *   `summary` is omitted).
 * - keyboard: the `<details>` disclosure and its table are natively operable; the
 *   chart itself is a static image with a full text equivalent (no focus trap).
 * - non-color: label + value on every table row; the line is one accent stroke.
 * - reduced-motion: the draw-on animation is disabled (geometry unchanged).
 */
export function Beatline({
  data,
  caption,
  summary,
  unit,
  height = STRIP_H,
  loading = false,
  emptyTitle,
  emptyHint,
  valueHeader,
  labelHeader,
  showDots = true,
}: {
  data: BeatPoint[];
  caption: string;
  summary?: string;
  unit?: string;
  height?: number;
  loading?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  valueHeader?: string;
  labelHeader?: string;
  showDots?: boolean;
}) {
  const reduced = usePrefersReducedMotion();
  const lang = useLang();
  const L = (k: StrKey) => localize(lang, k);
  const summaryId = useRef(`chart-sum-${(seq += 1)}`).current;

  if (loading) {
    return (
      <figure className="chart" role="group" aria-label={caption} aria-busy="true">
        <p className="chart-summary">{caption}</p>
        <div className="skeleton" style={{ height, borderRadius: 'var(--menq-radius-md)' }} />
      </figure>
    );
  }

  if (data.length === 0) {
    return (
      <figure className="chart" role="group" aria-label={caption}>
        <div className="chart-empty">
          <EmptyState glyph="◌" title={emptyTitle ?? L('emptyTitle')} hint={emptyHint} />
        </div>
      </figure>
    );
  }

  const values = data.map((d) => d.value);
  const path = buildLinePath(values, STRIP_W, height);
  const dots = showDots ? pointCoords(values, STRIP_W, height) : [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const last = values[values.length - 1];
  const u = unit ? ` ${unit}` : '';
  const autoSummary = beatSummary(lang, caption, data.length, min, max, last, u);
  const text = summary ?? autoSummary;

  return (
    <figure className="chart" role="group" aria-label={caption}>
      {/* accessible one-line summary; the svg is labelled by it */}
      <p id={summaryId} className="chart-summary">{text}</p>

      <svg
        className="chart-plot"
        viewBox={`0 0 ${STRIP_W} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-labelledby={summaryId}
      >
        <line x1="0" y1={height / 2} x2={STRIP_W} y2={height / 2} className="chart-baseline" />
        <path d={path} className={`chart-line ${reduced ? '' : 'chart-line--draw'}`} />
        {dots.map((pt, i) => (
          <circle key={data[i].label + i} cx={pt.x} cy={pt.y} r={4} className="chart-dot">
            <title>{`${data[i].label}: ${data[i].value}${u}`}</title>
          </circle>
        ))}
      </svg>

      {/* data-table fallback — every point reachable as text */}
      <details className="chart-table">
        <summary>{L('showDataTable')}</summary>
        <table>
          <caption className="chart-caption">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">{labelHeader ?? L('labelHeader')}</th>
              <th scope="col" className="chart-num">{valueHeader ?? L('valueHeader')}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d, i) => (
              <tr key={d.label + i}>
                <th scope="row">{d.label}</th>
                <td className="chart-num">{d.value}{u}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// StripChart — the INTERACTIVE beatline/strip variant (Activity's ECG strip).
//
// Where `Beatline` is a static image with a text equivalent, `StripChart` is a
// live, keyboard-driven strip: a deterministic ECG trace (decorative) overlaid
// with roving-focus "blip" buttons, one per data point, plus a freeze/select
// affordance. It is fully controlled — the page owns `selected`/`opened`/`frozen`
// (so it can drive a detail panel, live region and vitals) and the primitive owns
// the geometry, the roving tabindex, and the keyboard model.
//
// Keyboard (on the focusable strip group):
//   ← ↑ / → ↓   scrub selection (clamped, no wrap)   Home / End  first / last
//   Enter       open the selected blip's detail        Space       freeze / unfreeze
//   Esc         close an open detail
// Non-color: every blip carries a text `label` (aria-label + title); selection and
// open state are exposed via aria-pressed + a shape/scale change, not hue alone.
// Reduced-motion: the sweep, the blip reveal and the dot transitions are disabled.
// ─────────────────────────────────────────────────────────────────────────────

export interface StripPoint {
  /** Stable key. */
  id: string;
  /** Accessible label for this blip (aria-label + title). */
  label: string;
}

export function StripChart({
  points,
  selected,
  opened = null,
  frozen = false,
  sweep = false,
  plot = false,
  beats = 8,
  ariaLabel,
  onSelect,
  onOpen,
  onToggleFreeze,
  onCloseOpened,
}: {
  points: StripPoint[];
  selected: number;
  opened?: number | null;
  frozen?: boolean;
  sweep?: boolean;
  plot?: boolean;
  beats?: number;
  ariaLabel: string;
  onSelect: (i: number) => void;
  onOpen: (i: number) => void;
  onToggleFreeze: () => void;
  onCloseOpened: () => void;
}) {
  const reduced = usePrefersReducedMotion();
  const blipRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const gridId = useRef(`strip-grid-${(seq += 1)}`).current;
  // Recompute the deterministic trace only when the beat count changes.
  const path = React.useMemo(() => buildECG(STRIP_W, STRIP_H, beats), [beats]);

  // Keep the roving-tabindex focus in sync with the selected blip after the
  // wrapper handles an arrow key (but never steal focus from outside the strip).
  useEffect(() => {
    const el = blipRefs.current[selected];
    if (el && document.activeElement && el.closest('.strip')?.contains(document.activeElement)) {
      el.focus();
    }
  }, [selected]);

  const move = (delta: number) => {
    if (points.length === 0) return;
    onSelect(Math.max(0, Math.min(points.length - 1, selected + delta)));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (points.length === 0) return;
    switch (e.key) {
      case ' ':
      case 'Spacebar':
        e.preventDefault();            // Space → freeze (not scroll / not blip click)
        onToggleFreeze();
        break;
      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault();
        move(1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        move(-1);
        break;
      case 'Home':
        e.preventDefault();
        onSelect(0);
        break;
      case 'End':
        e.preventDefault();
        onSelect(points.length - 1);
        break;
      case 'Enter':
        e.preventDefault();            // Enter → open the focused beat's detail
        onOpen(selected);
        break;
      case 'Escape':
        if (opened !== null) { e.preventDefault(); onCloseOpened(); }
        break;
      default:
        break;
    }
  };

  const stripClass = [
    'strip',
    plot ? 'strip--plot' : '',
    sweep && !frozen && !reduced ? 'strip--sweeping' : '',
    frozen ? 'strip--frozen' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={stripClass} role="group" tabIndex={0} aria-label={ariaLabel} onKeyDown={onKeyDown}>
      <svg
        className="strip-svg"
        viewBox={`0 0 ${STRIP_W} ${STRIP_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <pattern id={gridId} width="40" height="30" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 30" fill="none" className="strip-grid-line" />
          </pattern>
        </defs>
        {plot && <rect x="0" y="0" width={STRIP_W} height={STRIP_H} fill={`url(#${gridId})`} />}
        <line x1="0" y1={STRIP_H / 2} x2={STRIP_W} y2={STRIP_H / 2} className="strip-baseline" />
        <path d={path} className="strip-trace" fill="none" />
        {sweep && !reduced && <rect className="strip-sweep" x="0" y="0" width="3" height={STRIP_H} />}
      </svg>

      <div className="strip-blips">
        {points.map((p, i) => {
          const pct = ((i + 0.5) / points.length) * 100;
          const cls = [
            'strip-blip',
            i === selected ? 'strip-blip--sel' : '',
            i === opened ? 'strip-blip--open' : '',
          ].filter(Boolean).join(' ');
          return (
            <button
              key={p.id}
              type="button"
              ref={(el) => { blipRefs.current[i] = el; }}
              className={cls}
              style={{ left: `${pct}%`, animationDelay: reduced ? undefined : `${Math.min(i, 20) * 24}ms` }}
              tabIndex={i === selected ? 0 : -1}
              aria-label={p.label}
              aria-pressed={i === opened}
              title={p.label}
              onClick={() => { onSelect(i); onOpen(i); }}
              onFocus={() => onSelect(i)}
            >
              <span className="strip-blip-dot" aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BarChart — accessible horizontal bar chart (Analytics' distribution plot).
//
// Reuses the same three patterns as `Beatline`: an accessible one-line summary the
// figure is labelled by, a single flat accent fill (color is never the signal), and
// a <details> data-table fallback listing every bar as text. Adds a focusable
// legend whose items toggle bars on/off (controlled via `hidden` + `onToggle`),
// each bar's share of the visible total, and a running total. Non-color signal:
// the legend button's pressed state + a struck-through label mark a hidden node;
// each bar shows its value and share% as text.
// ─────────────────────────────────────────────────────────────────────────────

export interface BarDatum {
  /** Stable key (legend toggle + table row identity). */
  key: string;
  label: string;
  value: number;
}

export function BarChart({
  data,
  caption,
  summary,
  unit,
  hidden,
  onToggle,
  legendLabel,
  showLabel,
  hideLabel,
  hiddenWord,
  allHiddenNote,
  totalLabel,
  nodeHeader,
  valueHeader,
  shareHeader,
  tableToggle,
  showTable = true,
}: {
  data: BarDatum[];
  caption: string;
  summary?: string;
  unit?: string;
  hidden?: ReadonlySet<string>;
  onToggle?: (key: string) => void;
  legendLabel?: string;
  showLabel?: string;
  hideLabel?: string;
  hiddenWord?: string;
  allHiddenNote?: string;
  totalLabel?: string;
  nodeHeader?: string;
  valueHeader?: string;
  shareHeader?: string;
  tableToggle?: string;
  showTable?: boolean;
}) {
  const lang = useLang();
  const L = (k: StrKey) => localize(lang, k);
  const hide = hidden ?? new Set<string>();
  const summaryId = useRef(`bar-sum-${(seq += 1)}`).current;
  const visible = data.filter((m) => !hide.has(m.key));
  const max = Math.max(0, ...visible.map((m) => m.value));
  const total = visible.reduce((sum, m) => sum + m.value, 0);
  const top = visible.reduce<BarDatum | null>((best, m) => (best && best.value >= m.value ? best : m), null);
  const u = unit ? ` ${unit}` : '';

  // Chart-owned labels: honour any caller override, else localize.
  const legendLabelT = legendLabel ?? L('legendLabel');
  const showLabelT = showLabel ?? L('showLabel');
  const hideLabelT = hideLabel ?? L('hideLabel');
  const hiddenWordT = hiddenWord ?? L('hiddenWord');
  const allHiddenNoteT = allHiddenNote ?? L('allHiddenNote');
  const totalLabelT = totalLabel ?? L('totalLabel');
  const nodeHeaderT = nodeHeader ?? L('nodeHeader');
  const valueHeaderT = valueHeader ?? L('valueHeader');
  const shareHeaderT = shareHeader ?? L('shareHeader');
  const tableToggleT = tableToggle ?? L('showDataTable');

  const autoSummary = barSummary(lang, visible.length, total, u, top);
  const text = summary ?? autoSummary;

  return (
    <div className="barchart">
      <p id={summaryId} className="chart-summary">{text}</p>

      {onToggle && (
        <div className="barchart-legend" role="group" aria-label={legendLabelT}>
          {data.map((m) => {
            const off = hide.has(m.key);
            return (
              <button
                key={m.key}
                type="button"
                className={`barchart-legend-item ${off ? 'barchart-legend-item--off' : ''}`}
                aria-pressed={!off}
                onClick={() => onToggle(m.key)}
                title={off ? showLabelT : hideLabelT}
              >
                <span className="barchart-legend-swatch" aria-hidden="true" />
                <span className="barchart-legend-label">{m.label}</span>
                {off && <span className="barchart-legend-state"> · {hiddenWordT}</span>}
              </button>
            );
          })}
        </div>
      )}

      {visible.length === 0 ? (
        <div className="barchart-empty muted">{allHiddenNoteT}</div>
      ) : (
        <div className="bar-chart" role="img" aria-labelledby={summaryId}>
          {visible.map((m, i) => {
            const pct = max > 0 ? (m.value / max) * 100 : 0;
            const share = total > 0 ? Math.round((m.value / total) * 100) : 0;
            return (
              <div className="bar-row" key={m.key} style={{ ['--enter' as string]: `${i * 55}ms` } as React.CSSProperties}>
                <div className="bar-label" title={m.label}>{m.label}</div>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="bar-value">{m.value}{u}<span className="bar-share"> · {share}%</span></div>
              </div>
            );
          })}
        </div>
      )}

      <div className="barchart-total row between">
        <span className="barchart-total-cap">{totalLabelT}</span>
        <span className="barchart-total-value">{total}{u}</span>
      </div>

      {showTable && (
        <details className="chart-table">
          <summary>{tableToggleT}</summary>
          <table>
            <caption className="chart-caption">{caption}</caption>
            <thead>
              <tr>
                <th scope="col">{nodeHeaderT}</th>
                <th scope="col" className="chart-num">{valueHeaderT}</th>
                <th scope="col" className="chart-num">{shareHeaderT}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((m) => {
                const share = total > 0 && !hide.has(m.key) ? Math.round((m.value / total) * 100) : 0;
                return (
                  <tr key={m.key}>
                    <th scope="row">{m.label}{hide.has(m.key) ? ` (${hiddenWordT})` : ''}</th>
                    <td className="chart-num">{m.value}{u}</td>
                    <td className="chart-num">{hide.has(m.key) ? '—' : `${share}%`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

export { buildECG, buildLinePath, pointCoords, ringPositions, STRIP_W, STRIP_H } from './geometry';
