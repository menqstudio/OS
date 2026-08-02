import React, { useRef } from 'react';
import '../ui.css';
import { EmptyState, usePrefersReducedMotion } from '../ui';
import { STRIP_W, STRIP_H, buildLinePath, pointCoords } from './geometry';

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
  emptyTitle = 'No data yet',
  emptyHint,
  valueHeader = 'Value',
  labelHeader = 'Point',
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
          <EmptyState glyph="◌" title={emptyTitle} hint={emptyHint} />
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
  const autoSummary =
    `${caption}: ${data.length} points, from ${min}${u} to ${max}${u}. Latest ${last}${u}.`;
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
        <summary>Show data table</summary>
        <table>
          <caption className="chart-caption">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">{labelHeader}</th>
              <th scope="col" className="chart-num">{valueHeader}</th>
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

export { buildECG, buildLinePath, pointCoords, STRIP_W, STRIP_H } from './geometry';
