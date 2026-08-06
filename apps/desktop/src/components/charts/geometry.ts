// Deterministic SVG geometry for the charts primitive. Pure functions — no
// randomness, no time, no data fetching — so the same inputs always yield the
// same path string. That determinism is what makes the charts testable and what
// lets the ECG cadence render identically on every paint.

/** Default beatline strip dimensions (mirrors Activity's ECG strip). */
export const STRIP_W = 1000;
export const STRIP_H = 150;

/**
 * buildECG — synthesize an ECG (P-QRS-T) waveform across `beats` complexes.
 * Presentation geometry only; carries no telemetry meaning. Lifted from the
 * Activity page so the same cadence is reusable as a chart baseline.
 */
export function buildECG(width: number, height: number, beats: number): string {
  const mid = height / 2;
  const seg = width / beats;
  let d = `M 0 ${mid}`;
  for (let i = 0; i < beats; i++) {
    const x = i * seg;
    const p = x + seg * 0.14;
    const q = x + seg * 0.42;
    const r = x + seg * 0.48;
    const s = x + seg * 0.54;
    const tw = x + seg * 0.74;
    d += ` L ${p.toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${(p + seg * 0.05).toFixed(1)} ${(mid - height * 0.09).toFixed(1)}`; // P
    d += ` L ${(p + seg * 0.1).toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${q.toFixed(1)} ${(mid + height * 0.07).toFixed(1)}`;                // Q
    d += ` L ${r.toFixed(1)} ${(mid - height * 0.42).toFixed(1)}`;                // R
    d += ` L ${s.toFixed(1)} ${(mid + height * 0.18).toFixed(1)}`;                // S
    d += ` L ${(s + seg * 0.04).toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${tw.toFixed(1)} ${(mid - height * 0.15).toFixed(1)}`;               // T
    d += ` L ${(tw + seg * 0.08).toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${(x + seg).toFixed(1)} ${mid.toFixed(1)}`;
  }
  return d;
}

/**
 * buildLinePath — deterministic polyline for a series of values, normalized to
 * the [pad, height-pad] band. `x` is spaced evenly; a flat/single series draws
 * a mid-height line. Returns an empty string for no data.
 */
export function buildLinePath(
  values: number[],
  width: number,
  height: number,
  pad = 6,
): string {
  if (values.length === 0) return '';
  const mid = height / 2;
  if (values.length === 1) return `M 0 ${mid.toFixed(1)} L ${width.toFixed(1)} ${mid.toFixed(1)}`;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const usable = height - pad * 2;
  return values
    .map((v, i) => {
      const x = i * stepX;
      const y = pad + (1 - (v - min) / span) * usable;
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
}

/**
 * ringPositions — evenly spaced node coordinates on a circle, in a 0..100
 * coordinate space (so absolutely-positioned nodes and an SVG overlay stay
 * aligned). Deterministic: the first node sits at the top (−90°) and the rest
 * proceed clockwise. A single node sits at the centre. Lifted from the Agents
 * lattice so the ring geometry is shared, pure and testable rather than bespoke.
 */
export function ringPositions(n: number, radius = 34): { x: number; y: number }[] {
  if (n <= 0) return [];
  const cx = 50;
  const cy = 50;
  const r = n === 1 ? 0 : radius;
  return Array.from({ length: n }, (_, i) => {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / n;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });
}

/** Even-x / normalized-y coordinates for each value (marker dots, deterministic). */
export function pointCoords(
  values: number[],
  width: number,
  height: number,
  pad = 6,
): { x: number; y: number }[] {
  if (values.length === 0) return [];
  const mid = height / 2;
  if (values.length === 1) return [{ x: width / 2, y: mid }];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const usable = height - pad * 2;
  return values.map((v, i) => ({
    x: i * stepX,
    y: pad + (1 - (v - min) / span) * usable,
  }));
}
